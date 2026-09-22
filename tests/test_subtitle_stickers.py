"""스티커: 모델 검증, 구간 옮기기, ASS 드로잉 이벤트, 이미지 overlay 필터."""

from pathlib import Path

import pysubs2
import pytest
from pydantic import ValidationError

from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_stickers import (
    STICKER_LABELS,
    STICKER_SHAPES,
    Sticker,
    add_sticker_events,
    clip_stickers,
    image_overlays,
    overlay_filter_graph,
    scaled_path,
    sticker_event_text,
)


def test_sticker_model_knows_its_kinds_and_rejects_bad_values():
    assert set(STICKER_SHAPES) | {"image"} == set(STICKER_LABELS)
    arrow = Sticker(kind="arrow-right", x=0.7, y=0.4, size=120, color="#ffe14d")
    assert arrow.color == "#FFE14D" and not arrow.is_image and arrow.motion_ms == 0
    assert Sticker(kind="image", image="wow.png").is_image
    for bad in (
        {"kind": "nope"},
        {"kind": "image"},
        {"kind": "image", "image": "../x.png"},
        {"kind": "image", "image": "x.jpg"},
        {"kind": "star", "color": "red"},
        {"kind": "star", "start": 3, "end": 2},
        {"kind": "star", "animation": "karaoke"},
        {"kind": "star", "x": 1.5},
    ):
        with pytest.raises(ValidationError):
            Sticker.model_validate(bad)
    spec = EditSpec(start=0, end=10, stickers=[{"kind": "heart"}])
    assert spec.stickers[0].kind == "heart" and EditSpec(start=0, end=10).stickers == []


def test_clip_stickers_keeps_overlapping_ones_and_rebases_their_times():
    stickers = [
        Sticker(kind="star", start=5, end=12),
        Sticker(kind="heart", start=30),
        Sticker(kind="check", start=2, end=8),
    ]
    clipped = clip_stickers(stickers, 10, 20)
    assert [(s.kind, s.start, s.end) for s in clipped] == [("star", 0, 2)]
    # 종료가 없는 스티커는 구간 끝까지, 구간 안에서 시작하면 그 시각부터입니다.
    assert [(s.start, s.end) for s in clip_stickers([Sticker(kind="star", start=12)], 10, 20)] == [
        (2, 10)
    ]


def test_event_text_scales_the_shape_positions_it_and_carries_motion():
    assert scaled_path("m 0 35 l 100 50", 1.6) == "m 0 56 l 160 80"
    text = sticker_event_text(
        Sticker(kind="arrow-right", x=0.5, y=0.25, size=200), 1080, 1920, 3000
    )
    assert text.startswith(
        "{\\pos(540,480)\\an5\\p1\\shad0\\1c&H4DE1FF&\\1a&H00&\\3c&H111111&\\bord2}"
    )
    assert text.endswith("m 0 70 l 110 70 l 110 24 l 200 100 l 110 176 l 110 130 l 0 130")
    # 크기 움직임은 좌표를 곱한 경로 위에 그대로 붙고, 이동 움직임은 \\pos 대신 \\move입니다.
    popped = sticker_event_text(Sticker(kind="star", animation="pop"), 1080, 1920, 3000)
    assert "\\fscx40\\fscy40" in popped and "\\pos(" in popped
    dropped = sticker_event_text(Sticker(kind="star", animation="bounce"), 1080, 1920, 3000)
    assert "\\move(540," in dropped and "\\pos(" not in dropped
    # 테두리만 있는 동그라미는 채움을 비우고 색을 선에 줍니다. 반투명 색은 알파로.
    ring = sticker_event_text(Sticker(kind="circle", color="#7FE3C680", outline=3), 720, 720, 1000)
    assert "\\1a&HFF&\\3c&HC6E37F&\\3a&H7F&\\bord3" in ring
    tilted = sticker_event_text(Sticker(kind="heart", angle=-15), 720, 720, 1000)
    assert "\\frz-15" in tilted
    with pytest.raises(ValueError):
        sticker_event_text(Sticker(kind="image", image="a.png"), 720, 720, 1000)


def test_add_sticker_events_puts_vectors_above_subtitles_and_skips_images():
    subs = pysubs2.SSAFile()
    stickers = [
        Sticker(kind="sparkle", start=0.5, end=2),
        Sticker(kind="image", image="a.png"),
        Sticker(kind="heart", start=1),
        Sticker(kind="check", start=5, end=6),  # 문서 길이(3초) 밖: 시작이 끝보다 뒤라 빠집니다.
    ]
    assert add_sticker_events(subs, stickers, width=1080, height=1920, duration=3) == 3
    events = [e for e in subs.events if e.style == "Sticker"]
    assert [(e.start, e.end, e.layer) for e in events] == [(500, 2000, 50), (1000, 3000, 50)]
    assert (
        "Sticker" in subs.styles
        and add_sticker_events(subs, [], width=1, height=1, duration=1) == 0
    )


def test_image_overlays_need_the_directory_and_build_a_filter_graph(tmp_path):
    (tmp_path / "wow.png").write_bytes(b"\x89PNG")
    stickers = [Sticker(kind="image", image="wow.png", x=0.5, y=0.2, size=200, start=1, end=2.5)]
    with pytest.raises(ValueError, match="R4_STICKERS_DIR"):
        image_overlays(stickers, None, width=1080, height=1920, duration=5)
    with pytest.raises(ValueError, match="없습니다"):
        image_overlays(
            [Sticker(kind="image", image="no.png")], tmp_path, width=1080, height=1920, duration=5
        )
    overlays = image_overlays(stickers, tmp_path, width=1080, height=1920, duration=5)
    assert overlays[0].path == (tmp_path / "wow.png").resolve()
    assert (overlays[0].center_x, overlays[0].center_y, overlays[0].width) == (540, 384, 200)
    inputs, graph, out = overlay_filter_graph("scale=1080:1920,subtitles=c.ass", overlays)
    assert inputs == ["-i", str(tmp_path / "wow.png")]
    assert graph == (
        "[0:v]scale=1080:1920,subtitles=c.ass[base0];[1:v]scale=200:-1[s0];"
        "[base0][s0]overlay=x=540-w/2:y=384-h/2:enable='between(t,1.000,2.500)'[base1]"
    )
    assert out == "base1"
    assert image_overlays([Sticker(kind="star")], None, width=1, height=1, duration=1) == []


def test_worker_writes_vector_stickers_and_switches_to_filter_complex_for_images(
    tmp_path, monkeypatch
):
    from worker.rendering import RenderError, video_filter, video_filter_args, write_subtitles

    spec = EditSpec(
        start=10,
        end=20,
        cues=[Cue(start=11, end=13, text="안녕")],
        stickers=[
            Sticker(kind="arrow-down", start=12, end=15),
            Sticker(kind="image", image="wow.png", start=12),
        ],
    )
    path = tmp_path / "captions.ass"
    write_subtitles(path, spec)
    loaded = pysubs2.load(str(path))
    sticker_events = [e for e in loaded.events if e.style == "Sticker"]
    assert [(e.start, e.end) for e in sticker_events] == [(2000, 5000)]
    # 이미지 스티커는 디렉터리가 있어야 하고, 있으면 filter_complex로 바뀝니다.
    monkeypatch.delenv("R4_STICKERS_DIR", raising=False)
    with pytest.raises(ValueError, match="R4_STICKERS_DIR"):
        video_filter_args(spec, base_chain=video_filter(spec))
    (tmp_path / "wow.png").write_bytes(b"\x89PNG")
    monkeypatch.setenv("R4_STICKERS_DIR", str(tmp_path))
    args = video_filter_args(spec, base_chain=video_filter(spec))
    assert args[:2] == ["-i", str((tmp_path / "wow.png").resolve())]
    assert args[2] == "-filter_complex" and "between(t,2.000,10.000)" in args[3]
    assert args[-2:] == ["-map", "[base1]"]
    plain = EditSpec(start=0, end=5, stickers=[Sticker(kind="star")])
    assert video_filter_args(plain, base_chain="x")[:3] == ["-map", "0:v:0", "-vf"]
    # 합성 명령은 RenderError로 바꿔 알립니다.
    monkeypatch.delenv("R4_STICKERS_DIR")
    from worker import rendering

    monkeypatch.setattr(rendering, "ffmpeg_binary", lambda: "ffmpeg")
    source = tmp_path / "in.mp4"
    source.write_bytes(b"x")
    with pytest.raises(RenderError, match="R4_STICKERS_DIR"):
        rendering.render_clip(source, tmp_path / "out.mp4", spec)
    assert Path(tmp_path / "out.mp4").exists() is False


def test_image_stickers_survive_the_graph_render_path(tmp_path, monkeypatch):
    """구간·전환·잡음 제거를 쓰면 렌더가 그래프 경로로 갑니다. 거기서도 스티커가 붙어야 합니다.

    `video_filter_args`(단순 경로)에서만 오버레이를 붙이던 때에는 그래프 경로에서
    **아무 말 없이 스티커가 사라졌습니다.** 오류도 나지 않아 사람이 알 수 없습니다.
    """
    from pathlib import Path

    from pipeline.editing import EditSpec, Sticker
    from worker.rendering import graph_command, simple

    monkeypatch.setenv("R4_STICKERS_DIR", str(tmp_path))
    (tmp_path / "wow.png").write_bytes(b"\x89PNG")
    stickers = [Sticker(kind="image", image="wow.png", start=1.0, end=3.0)]
    spec = EditSpec(start=0, end=10, stickers=stickers, denoise="soft")

    assert not simple(spec), "잡음 제거가 있으면 그래프 경로여야 합니다"
    command = graph_command(Path("/tmp/a.mp4"), tmp_path, spec, None, True)
    assert "-i" in command and str((tmp_path / "wow.png").resolve()) in command
    graph = command[command.index("-filter_complex") + 1]
    assert "overlay=" in graph and "[sticker0]" in graph
    # 영상 출력이 스티커를 얹은 마지막 라벨이어야 합니다(안 그러면 그려도 버려집니다).
    assert command[command.index("-map") + 1] == "[sticker0]"
