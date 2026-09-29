import copy
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_speaker_review import build, prepare  # noqa: E402


class SpeakerReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with wave.open(str(self.root / "sample.wav"), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
            wav.writeframes(b"\x00\x00" * 16000)
        self.data = {
            "schema": 1,
            "source_video_sha256": "a" * 64,
            "items": [
                {
                    "review_id": 0,
                    "audio_file": "sample.wav",
                    "audio_start": 0,
                    "audio_end": 1.04,
                    "candidate_start": 0.98,
                    "candidate_end": 1.04,
                    "human_speakers": ["speaker_1"],
                    "human_overlap": None,
                    "human_confidence": 0,
                    "reviewer": "</script><img src=x>",
                }
            ],
        }
        self.template, self.reviewed = self.root / "template.json", self.root / "reviewed.json"
        self.template.write_text(json.dumps(self.data))
        self.reviewed.write_text(json.dumps(self.data))

    def test_preserve_null_zero_and_partial_audio(self):
        result = prepare(self.template, self.reviewed)
        self.assertIsNone(result["received"]["items"][0]["human_overlap"])
        self.assertEqual(result["received"]["items"][0]["human_confidence"], 0)
        measurement = result["measurements"]["0"]
        self.assertFalse(measurement["candidate_fully_audible"])
        self.assertFalse(measurement["declared_duration_matches"])
        self.assertEqual(measurement["duration"], 1.0)

    def test_metadata_mutation_is_rejected(self):
        changed = copy.deepcopy(self.data)
        changed["items"][0]["candidate_end"] = 1
        self.reviewed.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            prepare(self.template, self.reviewed)

    def test_bad_labels_and_cohort_are_rejected(self):
        for key, value in [
            ("human_overlap", 0),
            ("human_confidence", True),
            ("human_confidence", 1.1),
            ("human_speakers", ["unknown", "speaker_0"]),
        ]:
            changed = copy.deepcopy(self.data)
            changed["items"][0][key] = value
            self.reviewed.write_text(json.dumps(changed))
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prepare(self.template, self.reviewed)
        self.reviewed.write_text(json.dumps({**self.data, "items": []}))
        with self.assertRaises(ValueError):
            prepare(self.template, self.reviewed)

    def test_audio_path_cannot_escape(self):
        self.data["items"][0]["audio_file"] = "../sample.wav"
        for path in (self.template, self.reviewed):
            path.write_text(json.dumps(self.data))
        with self.assertRaises(ValueError):
            prepare(self.template, self.reviewed)

    def test_truncated_payload_is_rejected(self):
        path = self.root / "sample.wav"
        path.write_bytes(path.read_bytes()[:-2])
        with self.assertRaises(ValueError):
            prepare(self.template, self.reviewed)

    def test_build_escapes_script_and_preserves_existing_output(self):
        out = self.root / "review-v2.html"
        build(self.template, self.reviewed, out)
        content = out.read_text()
        self.assertNotIn("</script><img", content)
        self.assertIn("\\u003c/script>", content)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            build(self.template, self.reviewed, out)
        self.assertEqual(out.read_text(), content)


if __name__ == "__main__":
    unittest.main()
