import copy
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_speaker_review import build, prepare  # noqa: E402
from import_speaker_review import audit, import_review  # noqa: E402


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

    def v2_submission(self):
        import hashlib

        self.video = self.root / "source.bin"
        self.video.write_bytes(b"synthetic-source")
        self.data["source_video_sha256"] = hashlib.sha256(self.video.read_bytes()).hexdigest()
        for path in (self.template, self.reviewed):
            path.write_text(json.dumps(self.data))
        prepared = prepare(self.template, self.reviewed)
        submitted = copy.deepcopy(self.data)
        submitted["items"][0]["annotation_scope"] = "candidate"
        submitted["review_ui"] = {
            "version": 2,
            "template_sha256": prepared["template_sha256"],
            "received_sha256": prepared["received_sha256"],
            "measurements": prepared["measurements"],
            "score_approved": False,
        }
        self.submission = self.root / "submitted.json"
        self.submission.write_text(json.dumps(submitted))
        return submitted

    def test_import_preserves_raw_and_denominator_without_scoring(self):
        self.v2_submission()
        output = self.root / "imported"
        report = import_review(self.template, self.reviewed, self.submission, self.video, output)
        self.assertEqual(
            (output / "labels.received.json").read_bytes(), self.submission.read_bytes()
        )
        self.assertEqual(report["candidate_count"], 1)
        self.assertIn("candidate_audio_incomplete", report["items"][0]["reasons"])
        self.assertIn("missing_overlap", report["items"][0]["reasons"])
        self.assertNotIn("missing_confidence", report["items"][0]["reasons"])
        self.assertFalse(report["deploy_allowed"])
        self.assertIsNone(report["der"])
        self.assertNotIn(self.data["items"][0]["reviewer"], json.dumps(report))
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((output / "audit.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            import_review(self.template, self.reviewed, self.submission, self.video, output)

    def test_import_checks_provenance_and_boolean_types(self):
        original = self.v2_submission()
        for key, value in [("received_sha256", "0" * 64), ("score_approved", 0), ("version", True)]:
            changed = copy.deepcopy(original)
            changed["review_ui"][key] = value
            self.submission.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit(self.template, self.reviewed, self.submission, self.video)
        changed = copy.deepcopy(original)
        changed["items"][0]["audio_start"] = False
        self.submission.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            audit(self.template, self.reviewed, self.submission, self.video)

    def test_import_rejects_changed_audio_or_video(self):
        self.v2_submission()
        self.video.write_bytes(b"different-source")
        with self.assertRaises(ValueError):
            audit(self.template, self.reviewed, self.submission, self.video)
        self.video.write_bytes(b"synthetic-source")
        audio = self.root / "sample.wav"
        audio.write_bytes(audio.read_bytes()[:-2] + b"\x01\x01")
        with self.assertRaises(ValueError):
            audit(self.template, self.reviewed, self.submission, self.video)

    def test_import_preserves_uncertain_scope_and_unknown(self):
        submitted = self.v2_submission()
        for scope in (None, "context", "uncertain"):
            submitted["items"][0].update(annotation_scope=scope, human_speakers=["unknown"])
            self.submission.write_text(json.dumps(submitted))
            _, report = audit(self.template, self.reviewed, self.submission, self.video)
            self.assertEqual(report["candidate_count"], 1)
            self.assertIn("candidate_scope_unconfirmed", report["items"][0]["reasons"])
            self.assertIn("unknown_speaker", report["items"][0]["reasons"])

    def test_import_rejects_missing_scope_and_missing_annotation(self):
        submitted = self.v2_submission()
        for key in ("annotation_scope", "human_overlap"):
            changed = copy.deepcopy(submitted)
            del changed["items"][0][key]
            self.submission.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit(self.template, self.reviewed, self.submission, self.video)


if __name__ == "__main__":
    unittest.main()
