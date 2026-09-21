"""모션 프리셋: 동작 검증, ASS 명령 만들기, 조각별 동작, 프리셋 불러오기."""

import json

import pytest
from pydantic import ValidationError

from pipeline import subtitle_presets as presets_module
from pipeline.subtitle_presets import (
    BUILTIN_PRESETS,
    MotionPreset,
    MotionStep,
    PresetBox,
    all_presets,
    get_preset,
    load_preset,
    preset_offset,
    preset_runs,
    preset_tags,
    presets_by_pack,
    register_preset,
    resolve_preset,
)

BOX = PresetBox(left=200, top=1500, right=880, bottom=1600)


def tags(name: str, duration: int = 2000, **values) -> str:  # noqa: ANN003
    values.setdefault("anchor", (540, 1600))
    values.setdefault("box", BOX)
    values.setdefault("base_tag", "\\1c&HFFFFFF&")
    return preset_tags(get_preset(name), duration_ms=duration, **values)


def test_steps_reject_combinations_that_ass_cannot_draw():
    with pytest.raises(ValidationError):
        MotionStep(kind="shake", phase="in")  # 계속되는 동작은 hold만
    with pytest.raises(ValidationError):
        MotionStep(kind="move", phase="in")  # 방향이 필요합니다
    with pytest.raises(ValidationError):
        MotionStep(kind="reveal", phase="out")
    two_moves = [
        {"kind": "move", "direction": "up"},
        {"kind": "move", "direction": "down"},
    ]
    with pytest.raises(ValidationError, match="한 번만"):
        MotionPreset(name="mine", label="내 것", steps=two_moves)
    two_runs = [{"kind": "reveal"}, {"kind": "wave", "phase": "hold"}]
    with pytest.raises(ValidationError, match="한 번만"):
        MotionPreset(name="mine", label="내 것", steps=two_runs)
    # 흔들림과 떠다님은 둘 다 `\frz`를 계속 써서 섞으면 서로 덮어씁니다.
    spinning = [
        {"kind": "shake", "phase": "hold"},
        {"kind": "float", "phase": "hold", "direction": "vertical"},
    ]
    with pytest.raises(ValidationError, match="합쳐서 한 번만"):
        MotionPreset(name="mine", label="내 것", steps=spinning)
    assert MotionPreset(name="mine", label="엑스", steps=[{"kind": "fade"}]).pack == "user"


def test_entrance_steps_set_a_start_value_and_animate_back():
    # 아래에서 올라오며 서서히 보입니다. `\move`는 이벤트에 한 번만 나옵니다.
    assert tags("from-below") == (
        "\\alpha&HFF&\\move(540,1690,540,1600,0,340)\\t(0,220,\\alpha&H00&)"
    )
    # 크기는 넘어갔다 돌아오는 두 구간입니다.
    jump = tags("jump-out")
    assert jump.startswith("\\q2\\fscx28\\fscy28\\alpha&HFF&")
    assert (
        "\\t(0,211,\\fscx124\\fscy124)" in jump and "\\t(211,340,0.55,\\fscx100\\fscy100)" in jump
    )
    # 길이가 없으면(정지 화면) 아무 명령도 붙지 않습니다.
    assert tags("from-below", duration=0) == ""


def test_exit_steps_run_at_the_end_of_the_subtitle():
    out = tags("shrink-out", duration=3000)
    assert "\\t(2660,3000,\\fscx42\\fscy42)" in out and "\\t(2660,3000,\\alpha&HFF&)" in out
    # 사라지는 프리셋은 그라데이션 띠가 따라갈 이동이 없습니다.
    assert preset_offset(get_preset("shrink-out")) is None
    assert preset_offset(get_preset("from-below")) == (90, 340)


def test_repeated_movement_uses_a_far_rotation_origin():
    # `\pos`는 `\t`로 바꿀 수 없어 멀리 둔 `\org`을 아주 조금 돌려 위아래로 띄웁니다.
    bob = tags("bob", duration=1200)
    assert bob.startswith("\\q2\\org(4540,1600)\\frz0.2")
    assert bob.count("\\t(") >= 4
    # 아주 긴 자막도 명령 수가 한계를 넘지 않습니다.
    assert tags("bob", duration=120_000).count("\\t(") <= 80
    # 기준점이 없으면 이동을 흉내 낼 수 없어 건너뜁니다.
    assert "\\org(" not in tags("bob", anchor=None)


def test_wipe_needs_the_text_box_and_grows_from_one_side():
    assert tags("fill-up") == "\\clip(0,1624,1080,1624)\\t(0,520,\\clip(0,1476,1080,1624))"
    assert tags("unfold-right").startswith("\\clip(176,0,176,1920)")
    assert "\\clip(176,0,904,1920)" in tags("unfold-center")
    # 글자 사각형이 없으면 잘라내기를 빼고 나머지만 만듭니다.
    assert "\\clip(" not in tags("title-in-1", box=None)


def test_colour_flash_returns_to_the_colour_it_was_given():
    assert tags("white-flash").startswith("\\q2\\1c&HFFFFFF&")
    assert "\\t(0,260,\\1c&HFFFFFF&)" in tags("white-flash", base_tag="\\1c&HFFFFFF&")
    assert "\\t(0,260,\\1c&H00FFFF&)" in tags("white-flash", base_tag="\\1c&H00FFFF&")
    # 돌아갈 색을 주지 않으면 번쩍이지 않습니다.
    assert "\\1c" not in tags("white-flash", base_tag="")


def test_hold_steps_start_after_the_entrance_is_done():
    # 등장과 계속되는 움직임이 같은 값을 건드려도 싸우지 않게 순서를 둡니다.
    mochi = tags("mochi", duration=2000)
    assert "\\t(460," in mochi


def test_per_run_steps_stagger_each_letter():
    body = preset_runs(get_preset("surf"), "가나다", duration_ms=1500)
    assert body.count("{\\r") == 3
    assert "\\t(0," in body and "\\t(70," in body
    # 조각별 동작이 없는 프리셋은 글자를 그대로 둡니다.
    assert preset_runs(get_preset("from-below"), "가나다", duration_ms=1500) == "가나다"
    # 글리치는 글자마다 깜빡이며 좌우로 튑니다.
    glitch = preset_runs(get_preset("glitch-down"), "가나", duration_ms=1500)
    assert "\\3a&HFF&" in glitch and "\\fax" in glitch
    # 노래방은 움직임 모듈과 같은 코드를 씁니다(강조 색이 필요합니다).
    sung = preset_runs(
        get_preset("karaoke"),
        "가 나",
        duration_ms=1500,
        accent="\\1c&HFFE14D&",
        base="\\1c&HFFFFFF&",
    )
    assert "\\1c&HFFE14D&" in sung
    with pytest.raises(ValueError, match="강조 색"):
        preset_runs(get_preset("karaoke"), "가 나", duration_ms=1500)


def test_every_builtin_preset_makes_something_libass_can_draw():
    names = [preset.name for preset in BUILTIN_PRESETS]
    assert len(names) == len(set(names)) and len(names) >= 90
    for preset in BUILTIN_PRESETS:
        made = preset_tags(
            preset, duration_ms=2500, anchor=(540, 1600), box=BOX, base_tag="\\1c&HFFFFFF&"
        )
        runs = preset_runs(
            preset, "가나 다라", duration_ms=2500, accent="\\1c&HFFE14D&", base="\\1c&HFFFFFF&"
        )
        assert made or runs != "가나 다라", preset.name
        assert "{" not in made and "}" not in made, preset.name
    packs = presets_by_pack()
    assert set(packs) == {"basic", "short", "kinetic"}
    assert len(packs["kinetic"]) == 34
    assert sum(len(items) for items in packs.values()) == len(BUILTIN_PRESETS)


def test_presets_round_trip_through_json_and_a_user_directory(tmp_path, monkeypatch):
    mine = MotionPreset(
        name="my-slide",
        label="내 슬라이드",
        steps=[MotionStep(kind="move", direction="left", amount=50), MotionStep(kind="fade")],
    )
    path = tmp_path / "my-slide.json"
    path.write_text(mine.to_json(), encoding="utf-8")
    assert load_preset(path) == mine
    assert json.loads(mine.to_json())["steps"][0]["direction"] == "left"
    # 디렉터리를 가리키면 이름으로 찾을 수 있고, 내장 프리셋과 함께 나옵니다.
    monkeypatch.setenv("R4_PRESETS_DIR", str(tmp_path))
    assert get_preset("my-slide").label == "내 슬라이드"
    assert presets_by_pack()["user"] == [mine]
    # 망가진 파일은 건너뜁니다.
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert "my-slide" in all_presets()
    monkeypatch.delenv("R4_PRESETS_DIR")
    with pytest.raises(ValueError, match="모르는 프리셋"):
        get_preset("my-slide")
    # 파일 경로로 바로 줄 수도 있고, 등록하면 이름으로 찾힙니다.
    assert resolve_preset(path) == mine
    assert resolve_preset(None) is None
    # 등록은 실행 전체에 남으므로 다른 테스트로 새지 않게 빈 칸에 넣습니다.
    monkeypatch.setattr(presets_module, "_REGISTERED", {})
    register_preset(mine)
    assert get_preset("my-slide") == mine
    with pytest.raises(ValueError, match="읽지 못했습니다"):
        load_preset(tmp_path / "없는파일.json")


def test_templates_use_a_preset_instead_of_their_own_animation():
    from pipeline.subtitle_templates import TextBlock, get_template

    base = get_template("default")
    moved = base.with_preset("from-below")
    assert moved.animated and moved.moves and moved.animation_label == "아래 등장"
    assert not base.animated and base.animation_label == "없음"
    body = moved.event_text_layers("안녕 세상", duration_ms=2000, anchor=(540, 1600))[0][1]
    assert body.startswith("{\\alpha&HFF&\\move(540,1690,540,1600,0,340)")
    # 그라데이션 띠는 이동을 따라갑니다.
    gradient = get_template("sunset-jalnan").with_preset("from-below")
    strip = gradient.gradient_strips(
        TextBlock(left=200, top=1500, width=680, height=100), 1080, 1920
    )
    assert "\\t(0,340,\\clip(" in strip[1]
    # 노래방 프리셋은 `[[...]]` 강조를 빼서 색이 겹치지 않게 합니다.
    assert get_template("default").with_preset("karaoke").karaoke
    assert not moved.karaoke
    # 프리셋을 쓴 템플릿은 JSON으로 저장·복원됩니다.
    assert SubtitleTemplateRoundTrip(moved) == "from-below"
    with pytest.raises(ValueError, match="모르는 프리셋"):
        base.with_preset("nope-nope")


def SubtitleTemplateRoundTrip(template) -> str:  # noqa: N802
    from pipeline.subtitle_templates import SubtitleTemplate

    return SubtitleTemplate.model_validate_json(template.to_json()).preset


def test_worker_bakes_the_preset_chosen_in_the_editor(tmp_path):
    import pysubs2

    from pipeline.editing import Cue, EditSpec
    from worker.rendering import RenderError, write_subtitles

    spec = EditSpec(
        start=0,
        end=5,
        cues=[Cue(start=1, end=3, text="안녕 세상")],
        subtitle_preset="quick-zoom",
    )
    path = tmp_path / "captions.ass"
    write_subtitles(path, spec)
    text = next(e.text for e in pysubs2.load(str(path)).events if "안녕" in e.text)
    assert "\\fscx58\\fscy58" in text and "\\t(0,150,\\fscx100\\fscy100)" in text
    # 프리셋이 움직임보다 먼저입니다.
    both = EditSpec.model_validate(
        {**spec.model_dump(), "subtitle_preset": "quick-zoom", "subtitle_animation": "fade"}
    )
    write_subtitles(path, both)
    assert "\\fscx58" in pysubs2.load(str(path)).events[0].text
    # 모르는 프리셋은 렌더 오류로 알립니다.
    with pytest.raises(RenderError, match="모르는 프리셋"):
        write_subtitles(
            path, EditSpec.model_validate({**spec.model_dump(), "subtitle_preset": "nope-nope"})
        )


def test_amount_can_be_left_out_or_set_to_zero():
    # 비우면 종류별 기본값입니다(흔들림 3°).
    default = MotionPreset(
        name="shaky", label="흔들", steps=[MotionStep(kind="shake", phase="hold", ms=400)]
    )
    assert "\\frz3" in preset_tags(default, duration_ms=1000, anchor=(540, 1600))
    # 0도 뜻이 있습니다. 예전에는 비움과 구분되지 않아 기본값으로 바뀌었습니다.
    sharpen = MotionPreset(
        name="sharpen",
        label="또렷",
        steps=[MotionStep(kind="blur", phase="out", amount=0, ms=200)],
    )
    assert "\\t(800,1000,\\blur0)" in preset_tags(sharpen, duration_ms=1000, anchor=None)
    # 크기 0은 줄 높이가 사라지지 않게 아주 얇게 둡니다.
    assert "\\fscy1" in tags("split-vertical")
    # 내보낸 JSON에는 비운 값이 들어가지 않습니다.
    assert "amount" not in json.loads(default.to_json())["steps"][0]


def test_letters_can_appear_with_blur_zoom_or_spin():
    for name, tag in [
        ("letter-blur", "\\blur9"),
        ("letter-zoom", "\\fscx55"),
        ("letter-spin", "\\frz14"),
    ]:
        body = preset_runs(get_preset(name), "가나", duration_ms=1500)
        assert body.count("{\\r") == 2 and tag in body
        # 조각이 제 시각에 나타나고 값이 제자리로 돌아옵니다.
        assert "\\3a&HFF&" in body and "\\t(55,56," in body
    # 단어 단위는 단어마다 한 번입니다.
    assert preset_runs(get_preset("word-zoom"), "가나 다라", duration_ms=1500).count("{\\r") == 2
