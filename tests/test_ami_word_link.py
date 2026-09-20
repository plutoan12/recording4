import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from link_ami_words import link_words  # noqa: E402


def fixture(tmp_path):
    path = tmp_path / "manual.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "corpusResources/meetings.xml",
            '<meetings><meeting observation="TS3003a">'
            '<speaker nxt_agent="A" global_name="person"/></meeting></meetings>',
        )
        z.writestr(
            "words/TS3003a.A.words.xml",
            '<words><w starttime="0" endtime="1">hi</w>'
            '<w starttime="1" endtime="3">there</w>'
            '<w starttime="3" endtime="3" punc="true">.</w>'
            '<w punc="true">!</w></words>',
        )
    row = dict(rows=[dict(row=dict(timestamps_start=[0], timestamps_end=[3], speakers=["person"]))])
    rttm = "SPEAKER TS3003a 1 0 3 &lt;NA&gt; &lt;NA&gt; person &lt;NA&gt; &lt;NA&gt;"
    return path, row, rttm


def test_complete_row_match_and_boundary_preserved(tmp_path):
    path, row, rttm = fixture(tmp_path)
    result = link_words(path, row, rttm, "TS3003a", end=2)
    assert result["matched_full_turns"] == 1
    assert result["boundary_clipped_words"] == 1
    assert result["segments"][1]["original_end"] == 3
    assert result["segments"][1]["end"] == 2
    assert result["segments"][1]["text"] == "there"
    assert result["deploy_allowed"] is False


def test_other_meeting_or_changed_row_refused(tmp_path):
    path, row, rttm = fixture(tmp_path)
    with pytest.raises(ValueError, match="meeting"):
        link_words(path, row, rttm, "TS3004a", end=2)
    row["rows"][0]["row"]["timestamps_end"] = [2.9]
    with pytest.raises(ValueError, match="Complete source"):
        link_words(path, row, rttm, "TS3003a", end=2)


def test_manual_word_coverage_must_match(tmp_path):
    path, row, rttm = fixture(tmp_path)
    row["rows"][0]["row"]["timestamps_end"] = [4]
    with pytest.raises(ValueError, match="coverage"):
        link_words(path, row, rttm.replace(" 0 3 ", " 0 4 "), "TS3003a", end=5)
