from worker.target_review import propose_target_reviews


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
