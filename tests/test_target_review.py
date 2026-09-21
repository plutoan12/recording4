import pytest

from worker.target_review import propose_target_reviews, qualify_target_reviews


def fixture():
    return [
        dict(
            text="a sufficiently long phrase",
            overlaps=[dict(start=0, end=1)],
            needs_review=False,
            words=[
                dict(
                    text="a sufficiently long phrase",
                    start=0,
                    end=1,
                    speaker="A",
                    timing_valid=True,
                    needs_review=False,
                )
            ],
        )
    ]


def test_target_match_never_changes_existing_assignment():
    reviews = fixture()
    output = propose_target_reviews(reviews, [dict(target="B", hypothesis=reviews[0]["text"])])
    word = output[0]["words"][0]
    assert word["speaker"] == "A"
    assert word["target_asr_review"]["candidates"] == ["B"]
    assert word["target_asr_review"]["applied"] is False
    assert word["needs_review"]
    assert "target_asr_review" not in reviews[0]["words"][0]


def test_both_targets_remain_ambiguous():
    reviews = fixture()
    output = propose_target_reviews(
        reviews, [dict(target=t, hypothesis=reviews[0]["text"]) for t in ["A", "B"]]
    )
    assert output[0]["words"][0]["target_asr_review"]["reason"] == "ambiguous_target_text"


def test_outside_overlap_and_incomplete_alignment_are_unchanged():
    reviews = fixture()
    reviews[0]["overlaps"] = []
    predictions = [dict(target="B", hypothesis=reviews[0]["text"])]
    assert propose_target_reviews(reviews, predictions) == reviews
    reviews = fixture()
    reviews[0]["words"][0]["text"] = "partial"
    assert propose_target_reviews(reviews, predictions) == reviews


def test_short_common_phrase_and_invalid_timing_are_not_proposed():
    reviews = fixture()
    assert propose_target_reviews(reviews, [dict(target="B", hypothesis="phrase")]) == reviews
    reviews[0]["words"][0]["timing_valid"] = False
    assert (
        propose_target_reviews(reviews, [dict(target="B", hypothesis=reviews[0]["text"])])
        == reviews
    )


def independent(target="B", **changes):
    row = dict(
        cue_index=0,
        word_index=0,
        target=target,
        text="a sufficiently long phrase",
        start=0,
        end=1,
        voice=dict(method="speaker_embedding", model_revision="voice-v1", match=0.8, margin=0.2),
        visual=dict(
            method="active_speaker_detection",
            model_revision="visual-v1",
            score_kind="calibrated_probability",
            calibration_revision="visual-calibration-v1",
            active_speaker_score=0.9,
        ),
    )
    row.update(changes)
    return row


def proposed(targets=("B",)):
    reviews = fixture()
    return propose_target_reviews(
        reviews, [dict(target=target, hypothesis=reviews[0]["text"]) for target in targets]
    )


def test_independent_voice_and_visual_evidence_only_qualifies_without_applying():
    output = qualify_target_reviews(
        proposed(),
        [independent()],
        trusted_visual_calibrations={("visual-v1", "visual-calibration-v1")},
    )
    word = output[0]["words"][0]
    review = word["target_asr_review"]
    assert review["independent_voice_verified"] is True
    assert review["independent_visual_verified"] is True
    assert review["qualified_for_reassignment"] is True
    assert review["qualification_reasons"] == []
    assert review["applied"] is False
    assert review["voice_provenance"]["model_revision"] == "voice-v1"
    assert review["visual_provenance"]["model_revision"] == "visual-v1"
    assert review["visual_provenance"]["score_kind"] == "calibrated_probability"
    assert review["visual_provenance"]["calibration_revision"] == "visual-calibration-v1"
    assert word["speaker"] == "A"
    assert word["needs_review"] is True


def test_missing_or_conflicting_independent_evidence_stays_unqualified():
    missing = qualify_target_reviews(proposed(), [])[0]["words"][0]["target_asr_review"]
    assert missing["qualification_reasons"] == ["missing_independent_evidence"]
    conflict = qualify_target_reviews(proposed(), [independent(), independent("A")])[0]["words"][0][
        "target_asr_review"
    ]
    assert conflict["qualified_for_reassignment"] is False
    assert "independent_target_conflict" in conflict["qualification_reasons"]


def test_ambiguous_target_text_cannot_be_qualified():
    review = qualify_target_reviews(proposed(("A", "B")), [independent()])[0]["words"][0][
        "target_asr_review"
    ]
    assert review["qualification_reasons"] == ["ambiguous_target_text"]
    assert review["qualified_for_reassignment"] is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"voice": {"method": "diarization", "match": 1, "margin": 1}}, "invalid_voice_provenance"),
        (
            {
                "voice": {
                    "method": "speaker_embedding",
                    "model_revision": "voice-v1",
                    "match": 0.59,
                    "margin": 0.2,
                }
            },
            "voice_match_below_threshold",
        ),
        (
            {
                "voice": {
                    "method": "speaker_embedding",
                    "model_revision": "voice-v1",
                    "match": 0.8,
                    "margin": 0.14,
                }
            },
            "ambiguous_voice_identity",
        ),
        (
            {"visual": {"method": "diarization", "active_speaker_score": 1}},
            "invalid_visual_provenance",
        ),
        (
            {
                "visual": {
                    "method": "active_speaker_detection",
                    "model_revision": "visual-v1",
                    "score_kind": "calibrated_probability",
                    "calibration_revision": "visual-calibration-v1",
                    "active_speaker_score": 0.69,
                }
            },
            "visual_speaker_below_threshold",
        ),
    ],
)
def test_weak_or_non_independent_support_is_rejected(changes, reason):
    review = qualify_target_reviews(proposed(), [independent(**changes)])[0]["words"][0][
        "target_asr_review"
    ]
    assert reason in review["qualification_reasons"]
    assert review["qualified_for_reassignment"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"start": 0.1},
        {"end": float("nan")},
        {"text": "different text"},
        {"cue_index": 1},
        {
            "voice": {
                "method": "speaker_embedding",
                "model_revision": "voice-v1",
                "match": 1.1,
                "margin": 0.2,
            }
        },
        {
            "visual": {
                "method": "active_speaker_detection",
                "model_revision": "visual-v1",
                "score_kind": "calibrated_probability",
                "calibration_revision": "visual-calibration-v1",
                "active_speaker_score": 2,
            }
        },
    ],
)
def test_independent_evidence_must_match_the_exact_reviewed_word(changes):
    with pytest.raises(ValueError):
        qualify_target_reviews(proposed(), [independent(**changes)])


def test_duplicate_independent_evidence_is_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        qualify_target_reviews(proposed(), [independent(), independent()])


def test_evidence_without_a_target_asr_proposal_is_rejected():
    with pytest.raises(ValueError, match="no target-ASR proposal"):
        qualify_target_reviews(fixture(), [independent()])


def test_applied_review_history_cannot_be_reset():
    review = proposed()
    review[0]["words"][0]["target_asr_review"]["applied"] = True
    with pytest.raises(ValueError, match="cannot be requalified"):
        qualify_target_reviews(review, [independent()])


def test_human_evidence_requires_attribution_and_preserves_it():
    row = independent(
        visual=dict(
            method="human_visual_review",
            reviewer_id="reviewer-1",
            reviewed_at="2026-09-20T13:00:00+09:00",
            active_speaker_score=1,
        )
    )
    evidence = qualify_target_reviews(proposed(), [row])[0]["words"][0]["target_asr_review"]
    assert evidence["visual_provenance"]["reviewer_id"] == "reviewer-1"
    row["visual"].pop("reviewer_id")
    with pytest.raises(ValueError, match="visual provenance"):
        qualify_target_reviews(proposed(), [row])


@pytest.mark.parametrize(
    ("visual", "expected_score_kind"),
    [
        (
            {
                "method": "active_speaker_detection",
                "model_revision": "visual-v1",
                "active_speaker_score": 0.9,
            },
            None,
        ),
        (
            {
                "method": "active_speaker_detection",
                "model_revision": "visual-v1",
                "score_kind": "raw_logit",
                "calibration_revision": "visual-calibration-v1",
                "active_speaker_score": 4.2,
            },
            "raw_logit",
        ),
        (
            {
                "method": "active_speaker_detection",
                "model_revision": "visual-v1",
                "score_kind": "calibrated_probability",
                "active_speaker_score": 0.9,
            },
            "calibrated_probability",
        ),
    ],
)
def test_machine_visual_evidence_requires_trusted_calibration_without_aborting(
    visual, expected_score_kind
):
    review = qualify_target_reviews(proposed(), [independent(visual=visual)])[0]["words"][0][
        "target_asr_review"
    ]
    assert review["qualified_for_reassignment"] is False
    assert "untrusted_visual_calibration" in review["qualification_reasons"]
    assert review["visual_provenance"].get("score_kind") == expected_score_kind


def test_trusted_visual_calibration_uses_normalized_provenance():
    visual = independent()["visual"]
    visual.update(
        model_revision=" visual-v1 ",
        score_kind=" calibrated_probability ",
        calibration_revision=" visual-calibration-v1 ",
    )
    review = qualify_target_reviews(
        proposed(),
        [independent(visual=visual)],
        trusted_visual_calibrations={("visual-v1", "visual-calibration-v1")},
    )[0]["words"][0]["target_asr_review"]
    assert review["qualified_for_reassignment"] is True


@pytest.mark.parametrize("trusted", [None, [["visual-v1", "visual-calibration-v1"]]])
def test_invalid_trusted_visual_calibration_has_fixed_error(trusted):
    with pytest.raises(ValueError, match="Invalid trusted visual calibration"):
        qualify_target_reviews(proposed(), [independent()], trusted_visual_calibrations=trusted)


def test_requalification_clears_stale_provenance():
    first = qualify_target_reviews(proposed(), [independent()])
    review = qualify_target_reviews(first, [])[0]["words"][0]["target_asr_review"]
    assert review["qualification_reasons"] == ["missing_independent_evidence"]
    assert "voice_provenance" not in review and "visual_provenance" not in review


def test_same_human_cannot_supply_both_independent_modalities():
    human = dict(reviewer_id="reviewer-1", reviewed_at="2026-09-20T13:00:00+09:00")
    row = independent(
        voice=dict(method="human_voice_reference", **human, match=1, margin=1),
        visual=dict(method="human_visual_review", **human, active_speaker_score=1),
    )
    review = qualify_target_reviews(proposed(), [row])[0]["words"][0]["target_asr_review"]
    assert review["qualified_for_reassignment"] is False
    assert "human_evidence_not_independent" in review["qualification_reasons"]
