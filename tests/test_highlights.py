"""숏폼 구간 추천. 장면 경계와 발화 구간만 보고 점수를 매기는 계산."""

from __future__ import annotations

import pytest

from pipeline.highlights import Highlight, covered, suggest

# 0~30 조용한 인트로, 30~150 말이 꽉 찬 본론, 150~180 마무리.
SCENES = [{"start": float(at), "end": at + 10.0} for at in range(0, 180, 10)]
SPEECH = [(30.0, 80.0), (85.0, 150.0)]


def test_covered_counts_only_the_overlap():
    assert covered((0.0, 10.0), [(5.0, 20.0)]) == pytest.approx(5.0)
    assert covered((0.0, 10.0), [(20.0, 30.0)]) == 0.0
    assert covered((0.0, 10.0), [(0.0, 4.0), (6.0, 8.0)]) == pytest.approx(6.0)


def test_the_talky_middle_beats_the_silent_intro():
    found = suggest(SCENES, SPEECH, duration=180, target=45)
    assert found, "추천이 하나는 나와야 합니다"
    best = max(found, key=lambda h: h.score)
    assert best.speech_ratio == pytest.approx(1.0)
    assert 30.0 <= best.start < 150.0


def test_silent_stretches_are_not_suggested():
    """말이 거의 없는 구간을 내밀지 않습니다."""
    found = suggest(SCENES, SPEECH, duration=180, target=45)
    assert all(item.speech_ratio > 0.3 for item in found)
    assert all(item.score >= 0.25 for item in found)


def test_nothing_is_suggested_when_there_is_no_speech():
    """말하는 영상 기준입니다. 음악·풍경 영상에서는 아무것도 내놓지 않습니다."""
    assert suggest(SCENES, [], duration=180, target=45) == []
    assert suggest(SCENES, [(0.0, 5.0)], duration=180, target=45) == []


def test_suggestions_never_overlap_and_respect_the_count():
    found = suggest(SCENES, SPEECH, duration=180, target=30, count=3)
    assert len(found) <= 3
    for earlier, later in zip(found, found[1:], strict=False):
        assert earlier.end <= later.start


def test_length_stays_inside_the_bounds_and_leans_to_the_target():
    found = suggest(SCENES, SPEECH, duration=180, target=40, minimum=20, maximum=60)
    assert found
    assert all(20 <= item.seconds <= 60 for item in found)
    # 목표에 가까울수록 점수가 높으므로 가장 좋은 후보는 목표 근처입니다.
    best = max(found, key=lambda h: h.score)
    assert abs(best.seconds - 40) <= 20


def test_a_video_without_scene_changes_still_gets_candidates():
    """전환이 없는 영상(고정 카메라)에서도 후보를 만듭니다."""
    found = suggest([], SPEECH, duration=180, target=45, count=3)
    assert found
    assert all(item.scene_cuts == 0 for item in found)


def test_candidates_start_and_end_on_scene_boundaries():
    edges = {float(at) for at in range(0, 190, 10)}
    for item in suggest(SCENES, SPEECH, duration=180, target=45):
        assert item.start in edges and item.end in edges


def test_scores_are_rounded_and_bounded():
    for item in suggest(SCENES, SPEECH, duration=180, target=45):
        assert 0.0 <= item.score <= 1.0
        assert isinstance(item, Highlight)


def test_a_zero_length_source_suggests_nothing():
    assert suggest(SCENES, SPEECH, duration=0, target=45) == []


def test_api_schedules_a_highlight_task(client, auth_headers, session, user):
    """추천은 무료 분석 작업입니다. 유료 호출이 없습니다."""
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
        json={"kind": "highlights", "target": 30},
    )
    assert response.status_code == 202, response.text
    task = session.get(MediaTask, uuid.UUID(response.json()["id"]))
    assert task.kind == "highlights"
    assert task.settings["target"] == 30
