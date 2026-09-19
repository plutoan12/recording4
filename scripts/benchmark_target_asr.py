#!/usr/bin/env python3
"""Offline DiCoW evaluation; inputs contain predicted turns, never oracle masks.

Reference text is used only after decoding for scoring. Dependencies and model
files are supplied locally so experiments cannot alter the production worker.
"""

import argparse
import gc
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from verify_transcribe import distance, squeeze


def stno_mask(turns, target, frames, start=0.0, duration=None):
    active_frames = frames if duration is None else min(frames, max(0, round(duration * 50)))
    activity = {}
    for turn in turns:
        label = turn["speaker"]
        active = activity.setdefault(label, np.zeros(frames, dtype=bool))
        a = max(0, round((turn["start"] - start) * 50))
        b = min(active_frames, round((turn["end"] - start) * 50))
        if b > a:
            active[a:b] = True
    own = activity.get(target, np.zeros(frames, dtype=bool))
    others = np.zeros(frames, dtype=bool)
    for label, active in activity.items():
        if label != target:
            others |= active
    return np.stack([~(own | others), own & ~others, ~own & others, own & others]).astype("float32")


def run_fingerprint(item, model_revision, quantized, ctc_weight):
    config = dict(item=item, revision=model_revision, quantized=quantized, ctc_weight=ctc_weight)
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def main():
    import torch
    from faster_whisper.audio import decode_audio
    from transformers import AutoFeatureExtractor, AutoModelForSpeechSeq2Seq, AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quantize", action="store_true")
    parser.add_argument("--ctc-weight", type=float, default=0.0)
    args = parser.parse_args()
    torch.set_num_threads(2)
    # HF local dynamic-module loading misses transitive relative imports in this
    # checkpoint. Seed the offline cache with its pinned, reviewed Python files.
    from transformers.dynamic_module_utils import HF_MODULES_CACHE

    cache = Path(HF_MODULES_CACHE) / "transformers_modules" / args.model.name
    cache.mkdir(parents=True, exist_ok=True)
    for code in args.model.glob("*.py"):
        shutil.copy2(code, cache / code.name)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    extractor = AutoFeatureExtractor.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=True,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    ).eval()
    if args.quantize:
        model = torch.ao.quantization.quantize_dynamic(
            model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
        )
    model.generation_config.ctc_weight = args.ctc_weight
    print("model_ready", flush=True)
    # Required by the official model's CTC-aware decoder.
    tokenizer.upper_cased_tokens = {}
    vocab = tokenizer.get_vocab()
    for token, index in vocab.items():
        lower = (
            token[:1] + token[1:2].lower() + token[2:]
            if token.startswith("Ġ")
            else token[:1].lower() + token[1:]
        )
        if lower != token and lower in vocab:
            tokenizer.upper_cased_tokens[vocab[lower]] = index
    if hasattr(model, "set_tokenizer"):
        model.set_tokenizer(tokenizer)
    rows = json.loads(args.output.read_text()) if args.output.exists() else []
    revision = (args.model / "revision.txt").read_text().strip()
    for item in json.loads(args.manifest.read_text()):
        fingerprint = run_fingerprint(item, revision, args.quantize, args.ctc_weight)
        path = Path(item["audio"])
        previous = next((r for r in rows if r["id"] == item["id"]), None)
        if (
            previous
            and previous.get("run_fingerprint") == fingerprint
            and previous["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            continue
        if previous:
            raise ValueError("Existing evidence differs; use a new output file to preserve it")
        audio = decode_audio(str(path), sampling_rate=16000)
        start = item.get("start", 0.0)
        end = item.get("end", len(audio) / 16000)
        if end - start > 30:
            raise ValueError("Each evaluation window must be <=30 seconds")
        audio = audio[int(start * 16000) : int(end * 16000)]
        features = extractor(
            audio, sampling_rate=16000, return_tensors="pt", return_attention_mask=True
        )
        mask = stno_mask(
            item["turns"],
            item["target"],
            features.input_features.shape[-1] // 2,
            start,
            len(audio) / 16000,
        )
        with torch.inference_mode():
            tokens = model.generate(
                input_features=features.input_features.float(),
                attention_mask=features.attention_mask,
                stno_mask=torch.from_numpy(mask).unsqueeze(0).float(),
                language=item["language"],
                task="transcribe",
                return_timestamps=False,
                max_new_tokens=200,
                num_beams=1,
                do_sample=False,
            )
        text = tokenizer.batch_decode(tokens, skip_special_tokens=True)[0]
        ref = squeeze(item["reference"]).casefold()
        hyp = squeeze(text).casefold()
        row = dict(
            id=item["id"],
            language=item["language"],
            reference_characters=len(ref),
            errors=distance(ref, hyp),
            cer=distance(ref, hyp) / max(1, len(ref)),
            hypothesis=text,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        row.update(
            quantized=args.quantize,
            ctc_weight=args.ctc_weight,
            model_revision=revision,
            run_fingerprint=fingerprint,
            target=item["target"],
            generation_possibly_truncated=(
                int(tokens.shape[-1]) >= 200 and int(tokens[0, -1]) != tokenizer.eos_token_id
            ),
        )
        rows = [r for r in rows if r["id"] != item["id"]]
        rows.append(row)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in row.items() if k != "hypothesis"}), flush=True)
        # The checkpoint retains CTC scorer tensors after generate. Each manifest
        # row is an independent recording, so release those references explicitly.
        for name in ("ctc_rescorer", "encoder_logits", "stno_mask", "stno_mask_seek"):
            if hasattr(model, name):
                setattr(model, name, None)
        del tokens, features, audio, mask
        gc.collect()
        import ctypes

        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass  # Best effort; macOS and musl do not provide glibc malloc_trim.


if __name__ == "__main__":
    main()
