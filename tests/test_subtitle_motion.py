"""자막 움직임: ASS 애니메이션 명령 생성."""

import pytest

from pipeline.subtitle_motion import (
    ANIMATION_DEFAULT_MS,
    ANIMATION_LABELS,
    CONTINUOUS,
    ENTRANCE,
    PER_RUN,
    animate_runs,
    motion_tags,
    tokens,
)


def test_every_animation_has_a_label_a_default_and_a_group():
    kinds = set(ANIMATION_LABELS) - {"none"}
    assert kinds == ENTRANCE | CONTINUOUS | PER_RUN
    assert set(ANIMATION_DEFAULT_MS) == set(ANIMATION_LABELS)
    assert ANIMATION_LABELS["none"] == "없음"


def test_none_and_per_run_kinds_add_no_event_level_tags():
    assert motion_tags("none", 300, duration_ms=2000, anchor=(540, 1600)) == ""
    assert motion_tags("typewriter", 60, duration_ms=2000, anchor=(540, 1600)) == ""
    # 길이가 없는(정지 화면) 이벤트에는 붙지 않습니다.
    assert motion_tags("pop", 300, duration_ms=0, anchor=None) == ""


def test_entrance_tags_use_fade_scale_and_move():
    assert motion_tags("fade", 250, duration_ms=2000, anchor=None) == "\\fad(250,250)"
    # 페이드는 자막 길이의 절반을 넘지 않습니다.
    assert motion_tags("fade", 900, duration_ms=1000, anchor=None) == "\\fad(500,500)"
    pop = motion_tags("pop", 320, duration_ms=2000, anchor=None)
    assert pop.startswith("\\q2\\fscx40\\fscy40\\t(0,192,\\fscx112\\fscy112)")
    assert pop.endswith("\\t(192,320,\\fscx100\\fscy100)")
    slide = motion_tags("slide-up", 320, duration_ms=2000, anchor=(540, 1600))
    assert slide == "\\move(540,1670,540,1600,0,320)\\fad(192,0)"
    assert "\\move(540,1530,540,1600,0,320)" in motion_tags(
        "slide-down", 320, duration_ms=2000, anchor=(540, 1600)
    )
    bounce = motion_tags("bounce", 520, duration_ms=2000, anchor=(540, 1600))
    assert bounce.startswith("\\q2\\move(540,1510,540,1600,0,260)")
    assert "\\fscy84" in bounce and bounce.endswith("\\fscx100\\fscy100)")
    # 기준점이 없으면 이동 대신 팝으로 대신합니다.
    assert motion_tags("bounce", 520, duration_ms=2000, anchor=None) == pop.replace(
        "320", "520"
    ).replace("192", "312")
    assert motion_tags("zoom", 250, duration_ms=3000, anchor=None) == (
        "\\q2\\fad(250,0)\\t(0,3000,\\fscx110\\fscy110)"
    )


def test_continuous_tags_alternate_until_the_end_and_cap_the_count():
    wiggle = motion_tags("wiggle", 400, duration_ms=1000, anchor=None, angle=2)
    assert wiggle.startswith("\\frz5\\t(0,200,\\frz-1)\\t(200,400,\\frz5)")
    assert wiggle.count("\\t(") == 5
    pulse = motion_tags("pulse", 900, duration_ms=1800, anchor=None, glow=4)
    assert pulse.startswith("\\q2\\t(0,450,\\fscx105\\fscy105\\blur10)\\t(450,900,\\fscx100")
    assert "\\blur4)" in pulse
    # 아주 긴 자막도 명령 수가 80개를 넘지 않습니다.
    long = motion_tags("wiggle", 100, duration_ms=60_000, anchor=None)
    assert long.count("\\t(") <= 80


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="모르는 움직임"):
        motion_tags("spin", 300, duration_ms=1000, anchor=None)


def test_tokens_keep_override_blocks_and_line_breaks_whole():
    assert tokens("a{\\fnX}b\\Nc d") == ["a", "{\\fnX}", "b", "\\N", "c", " ", "d"]


def test_typewriter_reveals_each_visible_character_and_reapplies_state():
    out = animate_runs("typewriter", "가나 다", 60, duration_ms=2000, prefix="\\blur8")
    # 공백은 시간을 쓰지 않고 명령도 붙지 않습니다.
    assert out == (
        "{\\r\\blur8\\3a&HFF&\\4a&HFF&\\1a&HFF&\\t(0,1,\\3a&H00&\\4a&H00&\\1a&H00&)}가"
        "{\\r\\blur8\\3a&HFF&\\4a&HFF&\\1a&HFF&\\t(60,61,\\3a&H00&\\4a&H00&\\1a&H00&)}나 "
        "{\\r\\blur8\\3a&HFF&\\4a&HFF&\\1a&HFF&\\t(120,121,\\3a&H00&\\4a&H00&\\1a&H00&)}다"
    )
    # 속 빈 글자는 채움 투명도를 건드리지 않습니다.
    hollow = animate_runs("typewriter", "가", 60, duration_ms=2000, hollow=True)
    assert "\\1a" not in hollow and "\\3a&HFF&\\4a&HFF&" in hollow
    # 짧은 자막이면 70% 안에 다 나오도록 간격을 줄입니다.
    fast = animate_runs("typewriter", "가나다라마", 60, duration_ms=200, prefix="")
    assert "\\t(28,29," in fast and "\\t(112,113," in fast
    # 앞에 나온 명령(이모지 글꼴, 강조 색)은 `\\r` 뒤에 다시 적어 상태를 지킵니다.
    styled = animate_runs("typewriter", "{\\1c&H0000FF&}가{\\fnNoto Emoji}🍓", 60, duration_ms=2000)
    assert "{\\r\\1c&H0000FF&\\fnNoto Emoji\\3a&HFF&" in styled


def test_word_pop_and_karaoke_work_per_word_across_line_breaks():
    popped = animate_runs("word-pop", "안녕 세상\\N반가워", 200, duration_ms=2000)
    assert popped.count("\\fscy130\\t(") == 3
    assert "\\t(0,1,\\3a&H00&" in popped and "\\t(200,201," in popped and "\\t(400,401," in popped
    assert "\\N" in popped
    sung = animate_runs(
        "karaoke",
        "말하는 단어가 빛나요",
        0,
        duration_ms=3000,
        accent="\\1c&H4DE1FF&",
        base="\\1c&HFFFFFF&",
    )
    words = sung.split(" ")
    assert words[0].startswith("{\\r\\t(0,1,\\1c&H4DE1FF&)\\t(1000,1001,\\1c&HFFFFFF&)}")
    assert words[1].startswith("{\\r\\t(1000,1001,\\1c&H4DE1FF&)\\t(2000,2001,\\1c&HFFFFFF&)}")
    # 마지막 단어는 끝까지 강조한 채 둡니다.
    assert words[2] == "{\\r\\t(2000,2001,\\1c&H4DE1FF&)}빛나요"
    with pytest.raises(ValueError, match="강조 색"):
        animate_runs("karaoke", "가", 0, duration_ms=1000)
    # 조각별 움직임이 아니거나 길이가 없으면 그대로입니다.
    assert animate_runs("pop", "가 나", 300, duration_ms=1000) == "가 나"
    assert animate_runs("word-pop", "가 나", 300, duration_ms=0) == "가 나"
    assert animate_runs("word-pop", "   ", 300, duration_ms=1000) == "   "
