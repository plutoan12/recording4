import json

import pysubs2
import pytest

from pipeline.template_factory import PRESETS, build, preview_html, scene_data, scene_jsx


def sample(text="안녕하세요.\n두 줄 자막입니다."):
    subs = pysubs2.SSAFile()
    event = pysubs2.SSAEvent(start=1000, end=3000)
    event.plaintext = text
    subs.append(event)
    return subs


@pytest.mark.parametrize("name", PRESETS)
def test_templates_bounds_and_timing(name):
    scene = scene_data(sample(), name)
    x, y, w, h = scene["slot"]
    assert 0 <= x < x + w <= 1920
    assert 0 <= y < y + h <= 1080
    assert scene["cues"][0]["start"] == 1
    assert scene["duration"] == 3.5


def test_overlap_rejected():
    subs = sample()
    subs.append(pysubs2.SSAEvent(start=2000, end=4000, text="overlap"))
    with pytest.raises(ValueError, match="겹칠"):
        scene_data(subs, "imac27")


def test_overflow_rejected():
    with pytest.raises(ValueError, match="넘습니다"):
        scene_data(sample("가" * 1000), "retro-message")


def test_html_escapes_untrusted_caption():
    scene = scene_data(sample("</script><script>alert(1)</script>"), "imac27")
    result = preview_html(scene)
    assert result.count("</script>") == 1
    assert "\\u003c/script>" in result


def test_jsx_relative_assets_and_editable_layers():
    subs = sample()
    script = scene_jsx(scene_data(subs, "imac27"), subs)
    assert "File($.fileName).parent" in script
    assert "Replaceable screen" in script
    assert "layers.addText" in script
    assert "SCENE" not in script
    assert "PAYLOAD" not in script


def setup_files(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    for name in ("pink.jpg", "imac27.png"):
        (assets / name).write_bytes(b"untouched source")
    source = tmp_path / "input.srt"
    source.write_text(sample().to_string("srt"), encoding="utf-8")
    return source, assets


def test_bundle_no_overwrite_and_report(tmp_path):
    source, assets = setup_files(tmp_path)
    output = tmp_path / "out"
    build(source, assets, output, ["imac27"])
    report = json.loads((output / "report.json").read_text())
    assert not report["templates"][0]["rendered"]
    assert (output / "imac27/assets/imac27.png").read_bytes() == b"untouched source"
    with pytest.raises(ValueError, match="덮어쓰지"):
        build(source, assets, output, ["imac27"])


def test_render_failure_does_not_publish_partial_bundle(tmp_path, monkeypatch):
    source, assets = setup_files(tmp_path)
    output = tmp_path / "out"

    def fail(*args):
        raise ValueError("render failed")

    monkeypatch.setattr("pipeline.template_factory.render_video", fail)
    with pytest.raises(ValueError, match="render failed"):
        build(source, assets, output, ["imac27"], render=True)
    assert not output.exists()
    assert not list(tmp_path.glob(".template-*"))


def test_missing_asset_does_not_publish(tmp_path):
    source, assets = setup_files(tmp_path)
    (assets / "pink.jpg").unlink()
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="이미지"):
        build(source, assets, output, ["imac27"])
    assert not output.exists()
