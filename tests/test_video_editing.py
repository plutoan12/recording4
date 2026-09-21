"""여러 구간 이어 붙이기 · 무음 제거 제안 · 배속/페이드/배경음악 · 미리보기 한 장.

FFmpeg를 실제로 부르는 것은 `tests/test_render_integration.py`에 있습니다. 여기서는
구간 계산과 필터 그래프, 작업·API 배선을 봅니다.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from adminapi.models import MediaTask, SourceAsset
from pipeline.cuts import apply_margin, keep_spans, kept_seconds, smooth, spans, within
from pipeline.editing import Cue, EditSpec, TimeSpan, concat_cues
from worker.rendering import complex_filter, simple, source_time, tempo_chain


@pytest.fixture
def asset(session, user):
    row = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="test.mp4",
        created_by_id=user.id,
        duration_seconds=Decimal("120"),
        width=1920,
        height=1080,
        upload_state="verified",
    )
    session.add(row)
    session.commit()
    return row


# ─── 남길 구간 고르기 ──────────────────────────────────────────────────────


def test_margin_widens_speech_on_both_sides():
    assert apply_margin([False, False, True, False, False], 1, 1) == [
        False,
        True,
        True,
        True,
        False,
    ]
    # 음수는 좁힙니다. 말 앞뒤를 오히려 깎습니다.
    assert apply_margin([False, True, True, True, False], -1, -1) == [
        False,
        False,
        True,
        False,
        False,
    ]


def test_short_keeps_and_short_cuts_are_smoothed_away():
    # 혼자 떨어진 한 칸짜리 남김은 없앱니다.
    assert smooth([False, True, False, False, False], min_cut=1, min_clip=2)[1] is False
    # 한 칸짜리 잘림은 메웁니다. 0.2초짜리 컷이 여러 번 들어가면 덜컥거립니다.
    assert smooth([True, True, False, True, True], min_cut=2, min_clip=1) == [True] * 5


def test_smoothing_stops_even_when_a_run_flips_forever():
    """둘 다보다 짧은 구간 하나는 참↔거짓을 오갑니다. 멈추지 않으면 작업이 굳습니다."""
    assert len(smooth([True], min_cut=5, min_clip=5)) == 1


def test_speech_becomes_keep_spans_with_margin():
    kept = keep_spans([(2.0, 4.0)], 10.0, margin=0.2, min_cut=0.5, min_clip=0.4)
    assert kept == [(1.8, 4.2)]
    assert kept_seconds(kept) == 2.4


def test_a_silent_file_keeps_nothing_and_an_empty_one_is_not_an_error():
    assert keep_spans([], 10.0) == []
    assert keep_spans([(0, 5)], 0) == []


def test_spans_and_within_clip_to_the_asked_window():
    assert spans([True, True, False, True], fps=2) == [(0.0, 1.0), (1.5, 2.0)]
    assert within([(0.0, 10.0)], 3.0, 6.0) == [(3.0, 6.0)]
    assert within([(0.0, 1.0)], 3.0, 6.0) == []


# ─── 편집 사양 ─────────────────────────────────────────────────────────────


def test_segments_must_be_inside_the_clip_in_order_and_short_enough():
    with pytest.raises(ValidationError, match="시작~끝 안에"):
        EditSpec(start=0, end=10, segments=[{"start": 5, "end": 20}])
    with pytest.raises(ValidationError, match="시간 순서대로"):
        EditSpec(start=0, end=100, segments=[{"start": 50, "end": 60}, {"start": 10, "end": 20}])
    with pytest.raises(ValidationError, match="숏폼 길이"):
        EditSpec(start=0, end=400, segments=[{"start": 0, "end": 200}])
    with pytest.raises(ValidationError, match="페이드"):
        EditSpec(start=0, end=4, fade_in=3, fade_out=3)


def test_a_long_source_is_fine_as_long_as_the_joined_result_is_short():
    """열 시간짜리 원본에서 세 조각을 고르는 것이 이 기능의 요점입니다."""
    spec = EditSpec(
        start=0,
        end=36000,
        segments=[{"start": 0, "end": 5}, {"start": 20000, "end": 20040, "speed": 4.0}],
    )
    # 원본은 열 시간이지만 결과는 5초 + 40/4초 = 15초입니다. 상한은 결과에만 겁니다.
    assert spec.output_seconds == 15.0
    assert len(spec.spans) == 2


def test_without_segments_nothing_changes():
    spec = EditSpec(start=10, end=40)
    assert spec.output_seconds == 30
    assert [(s.start, s.end, s.speed) for s in spec.spans] == [(10.0, 40.0, 1.0)]
    assert simple(spec) is True


def test_cues_move_onto_the_joined_timeline_and_shrink_with_speed():
    segments = [TimeSpan(start=0, end=5), TimeSpan(start=50, end=60, speed=2.0)]
    moved = concat_cues(
        [
            Cue(start=1, end=3, text="앞"),
            Cue(start=30, end=32, text="빠진 구간"),
            Cue(start=52, end=56, text="뒤"),
        ],
        segments,
    )
    assert [(c.start, c.end, c.text) for c in moved] == [(1.0, 3.0, "앞"), (6.0, 8.0, "뒤")]


def test_a_cue_clipped_to_less_than_a_frame_is_dropped():
    segments = [TimeSpan(start=0, end=5)]
    assert concat_cues([Cue(start=4.99, end=6, text="끝자락")], segments) == []


# ─── 필터 그래프 ───────────────────────────────────────────────────────────


def test_atempo_is_chained_because_one_filter_only_covers_half_to_double():
    assert tempo_chain(1.0) == ""
    assert tempo_chain(2.0) == ",atempo=2"
    assert tempo_chain(4.0) == ",atempo=2.0,atempo=2"


def test_the_old_single_cut_path_is_kept_for_plain_edits():
    assert simple(EditSpec(start=0, end=10)) is True
    assert simple(EditSpec(start=0, end=10, fade_in=1)) is False
    assert simple(EditSpec(start=0, end=10, segments=[{"start": 0, "end": 5}])) is False


def test_each_segment_is_trimmed_then_joined_and_inputs_are_split_first():
    spec = EditSpec(start=0, end=100, segments=[{"start": 0, "end": 5}, {"start": 50, "end": 60}])
    graph, audio = complex_filter(spec, audio="[0:a]", music=None)
    # 같은 입력을 두 번 쓰려면 먼저 나눠야 합니다.
    assert "[0:v]split=2[vin0][vin1]" in graph and "[0:a]asplit=2[ain0][ain1]" in graph
    assert "[vin1]trim=start=50.0:end=60.0" in graph
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]" in graph
    assert graph.endswith("[vout]") and audio == "[ac]"


def test_a_single_segment_does_not_split():
    graph, _ = complex_filter(EditSpec(start=0, end=10, fade_in=1), audio="[0:a]", music=None)
    assert "split" not in graph


def test_music_is_ducked_under_speech_and_mixed_without_halving_it():
    spec = EditSpec(start=0, end=10, music_asset_id=uuid.uuid4(), music_gain_db=-12)
    graph, audio = complex_filter(spec, audio="[0:a]", music="[1:a]")
    assert "volume=-12.0dB" in graph
    assert "sidechaincompress" in graph
    # normalize=0이 아니면 입력 수만큼 나눠 말소리가 절반이 됩니다.
    assert "amix=inputs=2:normalize=0:duration=first[aout]" in graph and audio == "[aout]"


def test_music_without_ducking_just_mixes():
    spec = EditSpec(start=0, end=10, music_asset_id=uuid.uuid4(), music_duck=False)
    graph, _ = complex_filter(spec, audio="[0:a]", music="[1:a]")
    assert "sidechaincompress" not in graph and "amix=inputs=2" in graph


def test_fades_are_placed_at_the_end_of_the_joined_result():
    spec = EditSpec(start=0, end=10, fade_in=0.5, fade_out=1.0)
    graph, _ = complex_filter(spec, audio="[0:a]", music=None)
    assert "fade=t=in:st=0:d=0.5" in graph and "fade=t=out:st=9.0:d=1.0" in graph
    assert "afade=t=out:st=9.0:d=1.0" in graph


def test_preview_time_maps_back_onto_the_source():
    spec = EditSpec(
        start=0, end=100, segments=[{"start": 0, "end": 5}, {"start": 50, "end": 60, "speed": 2.0}]
    )
    assert [source_time(spec, at) for at in (0, 2, 5, 7)] == [0.0, 2.0, 50.0, 54.0]


# ─── API 배선 ──────────────────────────────────────────────────────────────


def test_silence_suggestion_is_queued_once_at_a_time(client, auth_headers, asset, session):
    first = client.post(
        f"/source-assets/{asset.id}/silence", headers=auth_headers, json={"min_cut": 0.6}
    )
    assert first.status_code == 202 and first.json()["kind"] == "silence"
    again = client.post(f"/source-assets/{asset.id}/silence", headers=auth_headers, json={})
    assert again.json()["id"] == first.json()["id"]
    task = session.get(MediaTask, uuid.UUID(first.json()["id"]))
    assert task.settings["min_cut"] == 0.6 and task.settings["margin"] == 0.2


def test_preview_frame_needs_a_time_inside_the_result(client, auth_headers, asset):
    spec = {"start": 0, "end": 10}
    body = {"at": 20, "spec": spec}
    assert (
        client.post(
            f"/source-assets/{asset.id}/preview-frame", headers=auth_headers, json=body
        ).status_code
        == 422
    )
    body["at"] = 3
    response = client.post(
        f"/source-assets/{asset.id}/preview-frame", headers=auth_headers, json=body
    )
    assert response.status_code == 202 and response.json()["kind"] == "preview"


def test_preview_url_waits_until_the_frame_exists(client, auth_headers, asset, session, storage):
    response = client.post(
        f"/source-assets/{asset.id}/preview-frame",
        headers=auth_headers,
        json={"at": 1, "spec": {"start": 0, "end": 10}},
    )
    task_id = response.json()["id"]
    assert (
        client.get(f"/media-tasks/{task_id}/preview-url", headers=auth_headers).status_code == 409
    )
    task = session.get(MediaTask, uuid.UUID(task_id))
    task.result = {"storage_key": "previews/x.png"}
    session.commit()
    url = client.get(f"/media-tasks/{task_id}/preview-url", headers=auth_headers).json()["url"]
    assert "previews/x.png" in url


def test_preview_url_is_only_for_preview_tasks(client, auth_headers, asset, session):
    task = MediaTask(source_asset_id=asset.id, kind="scenes", settings={})
    session.add(task)
    session.commit()
    assert (
        client.get(f"/media-tasks/{task.id}/preview-url", headers=auth_headers).status_code == 404
    )
