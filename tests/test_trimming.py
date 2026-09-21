"""무음 자동 컷. 남길 토막 계산과 시간축 다시 매핑, FFmpeg 필터 문자열."""

from __future__ import annotations

import pytest

from pipeline.editing import Cue, EditSpec, TrimSettings, Word
from pipeline.subtitle_stickers import Sticker
from pipeline.trimming import (
    keeps,
    kept_seconds,
    moved,
    moved_cues,
    moved_span,
    moved_words,
    select_expression,
    trims,
)
from worker.rendering import (
    RenderError,
    audio_filter_args,
    clip_keeps,
    trim_filters,
    trimmed_spec,
)

SPEECH = [(0.5, 2.0), (5.0, 7.0)]


def test_silence_between_speech_is_dropped_and_speech_is_padded():
    kept = keeps(SPEECH, start=0, end=10, settings=TrimSettings(pad=0.1))
    assert kept == [(0.4, 2.1), (4.9, 7.1)]
    # 10초가 3.9초로 줄었습니다.
    assert kept_seconds(kept) == pytest.approx(3.9)
    assert trims(kept)


def test_a_short_pause_is_left_alone():
    """숨 쉬는 자리까지 없애면 말이 붙어 듣기 나쁩니다."""
    kept = keeps([(0.0, 2.0), (2.3, 4.0)], start=0, end=4, settings=TrimSettings(pad=0))
    assert kept == [(0.0, 4.0)]
    assert not trims(kept)


def test_a_scrap_too_short_to_keep_is_dropped():
    kept = keeps(
        [(0.0, 3.0), (9.9, 10.0)], start=0, end=10, settings=TrimSettings(pad=0, min_keep=0.4)
    )
    assert kept == [(0.0, 3.0)]


def test_no_speech_found_cuts_nothing():
    """빈 영상을 내놓느니 원본 그대로가 낫습니다."""
    assert keeps([], start=0, end=10) == [(0.0, 10)]
    assert keeps([(50.0, 60.0)], start=0, end=10) == [(0.0, 10)]


def test_speech_outside_the_clip_is_ignored_and_the_rest_is_rebased():
    kept = keeps([(0.0, 1.0), (12.0, 14.0)], start=10, end=20, settings=TrimSettings(pad=0))
    assert kept == [(2.0, 4.0)]


def test_too_many_segments_are_merged_back_from_the_shortest_gap():
    """필터 문자열이 끝없이 길어지지 않게 합니다."""
    from pipeline import trimming

    speech = [(float(at), at + 0.5) for at in range(0, 40, 2)]
    kept = keeps(speech, start=0, end=40, settings=TrimSettings(pad=0, min_gap=0.6, min_keep=0.1))
    assert len(kept) == 20
    monkeyed = trimming._cap(list(kept), 5)
    assert len(monkeyed) == 5
    # 붙이기만 하므로 처음과 끝은 그대로입니다.
    assert (monkeyed[0][0], monkeyed[-1][1]) == (kept[0][0], kept[-1][1])


def test_times_move_onto_the_joined_timeline():
    kept = [(0.0, 2.0), (5.0, 7.0)]
    assert moved(1.0, kept) == pytest.approx(1.0)
    assert moved(5.5, kept) == pytest.approx(2.5)  # 3초가 사라졌습니다
    assert moved(3.0, kept) is None  # 잘려 나간 자리
    assert moved(9.0, kept) is None


def test_cues_move_and_cues_inside_the_cut_are_dropped():
    kept = [(0.0, 2.0), (5.0, 7.0)]
    cues = [
        Cue(start=0.2, end=1.8, text="첫 말"),
        Cue(start=3.0, end=4.0, text="침묵 속 자막"),
        Cue(start=5.2, end=6.8, text="둘째 말"),
    ]
    moved_list = moved_cues(cues, kept)
    assert [(round(c.start, 2), round(c.end, 2), c.text) for c in moved_list] == [
        (0.2, 1.8, "첫 말"),
        (2.2, 3.8, "둘째 말"),
    ]


def test_word_times_move_together_and_are_dropped_when_one_is_cut_away():
    kept = [(0.0, 2.0), (5.0, 7.0)]
    inside = Cue(
        start=0.2,
        end=1.8,
        text="첫 말",
        words=[Word(start=0.2, end=1.0, text="첫"), Word(start=1.0, end=1.8, text="말")],
    )
    assert moved_words(inside.words, kept) == [
        Word(start=0.2, end=1.0, text="첫"),
        Word(start=1.0, end=1.8, text="말"),
    ]
    # 한 단어라도 잘려 나가면 글자와 맞지 않으므로 전부 버립니다.
    across = [Word(start=1.5, end=3.5, text="걸친"), Word(start=5.1, end=5.5, text="말")]
    assert moved_words(across, kept) is None


def test_a_span_that_survives_only_in_part_keeps_its_remaining_edges():
    assert moved_span(1.0, 6.0, [(0.0, 2.0), (5.0, 7.0)]) == pytest.approx((1.0, 3.0))
    assert moved_span(3.0, 4.0, [(0.0, 2.0), (5.0, 7.0)]) is None


KEPT = [(0.0, 2.0), (5.0, 7.0)]
EXPRESSION = "between(t,0.000,2.000)+between(t,5.000,7.000)"


def test_the_filter_expression_is_quoted_so_commas_are_not_separators():
    prefix, audio = trim_filters(KEPT)
    assert select_expression(KEPT) == EXPRESSION
    assert prefix == f"select='{EXPRESSION}',setpts=N/FRAME_RATE/TB,"
    assert audio == [f"aselect='{EXPRESSION}'", "asetpts=N/SR/TB"]


def test_nothing_to_cut_adds_no_filters():
    assert trim_filters([(0.0, 10.0)]) == ("", [])
    assert audio_filter_args(EditSpec(start=0, end=10), [(0.0, 10.0)]) == []


def test_denoise_runs_after_the_cut_in_one_audio_chain():
    """버릴 구간까지 잡음을 깎는 것은 헛일입니다. 자르기가 먼저입니다."""
    spec = EditSpec(start=0, end=10, denoise="strong")
    assert audio_filter_args(spec, KEPT) == [
        "-filter:a",
        f"aselect='{EXPRESSION}',asetpts=N/SR/TB,afftdn=nf=-35",
    ]
    # 자를 것이 없으면 잡음 제거만 남습니다.
    assert audio_filter_args(spec, [(0.0, 10.0)]) == ["-filter:a", "afftdn=nf=-35"]
    assert audio_filter_args(EditSpec(start=0, end=10, denoise="soft"), [(0.0, 10.0)]) == [
        "-filter:a",
        "afftdn=nf=-20",
    ]


def spec(**extra) -> EditSpec:
    return EditSpec(start=10, end=20, silence=TrimSettings(pad=0), **extra)


def test_clip_keeps_uses_the_speech_it_is_given(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    assert clip_keeps(source, spec(), [(11.0, 13.0), (16.0, 18.0)]) == [(1.0, 3.0), (6.0, 8.0)]


def test_clip_keeps_returns_the_whole_clip_when_trimming_is_off(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    assert clip_keeps(source, EditSpec(start=10, end=20), None) == [(0.0, 10.0)]


def test_the_trimmed_spec_starts_at_zero_with_everything_moved():
    kept = [(0.0, 2.0), (5.0, 7.0)]
    original = spec(
        cues=[Cue(start=15.2, end=16.8, text="둘째 말")],
        stickers=[Sticker(kind="arrow-right", start=15.0, end=16.0)],
    )
    moved_spec = trimmed_spec(original, kept)
    assert (moved_spec.start, moved_spec.end) == (0.0, 4.0)
    assert [(round(c.start, 2), c.text) for c in moved_spec.cues] == [(2.2, "둘째 말")]
    assert [(round(s.start, 2), round(s.end, 2)) for s in moved_spec.stickers] == [(2.0, 3.0)]
    # 이미 옮겨 놓았으므로 렌더가 다시 자르지 않습니다.
    assert moved_spec.silence is None


def test_cutting_down_to_almost_nothing_is_refused():
    with pytest.raises(RenderError):
        trimmed_spec(spec(), [(0.0, 0.2)])


def test_a_hand_picked_keep_list_wins_over_detection(tmp_path):
    """사람이 화면에서 고친 토막을 기계가 다시 덮지 않습니다."""
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    picked = EditSpec(start=10, end=20, silence=TrimSettings(), keep=[(0.0, 1.0), (4.0, 6.0)])
    assert clip_keeps(source, picked, [(11.0, 19.0)]) == [(0.0, 1.0), (4.0, 6.0)]


def test_a_keep_list_works_without_the_automatic_setting(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    picked = EditSpec(start=10, end=20, keep=[(0.0, 3.0)])
    assert clip_keeps(source, picked, None) == [(0.0, 3.0)]


@pytest.mark.parametrize(
    "keep",
    [
        [],
        [(2.0, 1.0)],
        [(5.0, 7.0), (0.0, 2.0)],
        [(0.0, 3.0), (2.0, 4.0)],
        [(0.0, 11.0)],
    ],
)
def test_an_unusable_keep_list_is_refused(keep):
    with pytest.raises(ValueError):
        EditSpec(start=10, end=20, keep=keep)


def test_the_trimmed_spec_clears_the_keep_list():
    """이미 옮겨 놓았으므로 렌더가 다시 자르면 안 됩니다."""
    moved_spec = trimmed_spec(
        EditSpec(start=10, end=20, keep=[(0.0, 2.0), (5.0, 7.0)]), [(0.0, 2.0), (5.0, 7.0)]
    )
    assert moved_spec.keep is None and moved_spec.silence is None


def test_api_schedules_a_silence_measuring_task(client, auth_headers, session, user):
    """자르기 전에 어디가 잘리는지 재 봅니다. 무료 분석 작업입니다."""
    import uuid
    from decimal import Decimal

    from adminapi.models import MediaTask, SourceAsset

    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="a.mp4",
        upload_state="verified",
        duration_seconds=Decimal("180"),
        width=1920,
        height=1080,
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()
    response = client.post(
        f"/source-assets/{asset.id}/analyze",
        headers=auth_headers,
        json={"kind": "silence", "start": 10, "end": 40, "settings": {"min_gap": 1.0}},
    )
    assert response.status_code == 202, response.text
    task = session.get(MediaTask, uuid.UUID(response.json()["id"]))
    assert task.kind == "silence"
    assert (task.settings["start"], task.settings["end"]) == (10, 40)
    assert task.settings["settings"]["min_gap"] == 1.0
