"""Probe gap candidates on both separator stems without assigning either stem to a speaker."""

import argparse
from difflib import SequenceMatcher
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def overlapping_text(segments, core_start, core_end, offset):
    words = []
    for segment in segments:
        for word in segment.words or []:
            start, end = float(word.start) + offset, float(word.end) + offset
            if max(start, core_start) < min(end, core_end):
                words.append(word.word)
    return " ".join(words)


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from faster_whisper import WhisperModel
    from scipy.signal import resample_poly
    from speechbrain.inference.separation import SepformerSeparation

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "proposals", "model", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    fingerprints = {name: sha256(getattr(args, name)) for name in ["audio", "proposals"]}
    proposal = load_json(args.proposals)
    if proposal["source_sha256"] != fingerprints["audio"]:
        raise ValueError("Proposal audio changed")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Require finite mono 16k audio")
    separator = SepformerSeparation.from_hparams(
        source=str(args.model), savedir="/tmp/additive-separator", run_opts={"device": "cpu"}
    )
    asr = WhisperModel(
        "small", device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True
    )
    audits = []
    for item in proposal["candidates"]:
        if not 0 <= item["start"] < item["end"] <= len(audio) / rate:
            raise ValueError("Invalid candidate interval")
        begin = max(0, int((item["start"] - 1) * rate))
        end = min(len(audio), int((item["end"] + 1) * rate))
        mixture8 = resample_poly(audio[begin:end], 1, 2).astype(np.float32)
        with torch.no_grad():
            separated = separator.separate_batch(torch.from_numpy(mixture8).unsqueeze(0))
        stems8 = separated.cpu().numpy()[0]
        if stems8.ndim != 2 or stems8.shape[1] != 2 or not np.isfinite(stems8).all():
            raise ValueError("Invalid separator output")
        expected = " ".join(word["text"] for word in item["words"])
        stems = []
        for channel in range(2):
            stem = resample_poly(stems8[:, channel], 2, 1).astype(np.float32)
            segments, _ = asr.transcribe(
                stem, language="en", beam_size=5, vad_filter=False, word_timestamps=True
            )
            text = overlapping_text(segments, item["start"], item["end"], begin / rate)
            stems.append(
                dict(
                    channel=channel,
                    text=text,
                    exact_match=normalize(text) == normalize(expected),
                    text_similarity=SequenceMatcher(
                        None, normalize(text), normalize(expected)
                    ).ratio(),
                )
            )
        audits.append(
            dict(
                id=item["id"],
                expected=expected,
                crop_start=begin / rate,
                crop_end=end / rate,
                stems=stems,
                any_exact_match=any(stem["exact_match"] for stem in stems),
                speaker_identity_proven=False,
                accepted=False,
            )
        )
    if any(sha256(getattr(args, name)) != digest for name, digest in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        audit=audits,
        sha256=fingerprints,
        accepted_words=0,
        speaker_identity_proven=False,
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(
        [
            dict(
                id=row["id"],
                any_exact_match=row["any_exact_match"],
                stem_matches=[stem["exact_match"] for stem in row["stems"]],
                stem_text_similarities=[stem["text_similarity"] for stem in row["stems"]],
            )
            for row in audits
        ]
    )


if __name__ == "__main__":
    main()
