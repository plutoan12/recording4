#!/usr/bin/env python3
"""소음과 겹말에서 전사가 얼마나 버티는지 잽니다.

지금까지 전사 품질은 **깨끗한 낭독 음성**으로만 쟀습니다(전체 CER 9.7%). 실제
영상에는 배경 소음이 깔리고 사람들이 말을 겹쳐 합니다. 거기서 몇 점인지 모른 채
"정확도를 올렸다"고 말할 수 없습니다.

재는 방법은 **아는 음성을 일부러 망가뜨리는 것**입니다. 원문을 아는 사람 목소리
표본에 잡음과 다른 사람 목소리를 정해진 크기로 섞고, 조건마다 글자 오류율(CER)을
잽니다. 섞는 크기는 SNR로 정합니다(`pipeline.noise`).

    docker run --rm -v /tmp/human-sample:/audio ... verify_robust.py --directory /audio

**손잡이 두 벌을 나란히 잽니다.** `--compare`를 주면 지금 설정과 후보 설정으로
같은 음성을 두 번 받아쓰고 조건마다 견줍니다. 한 번 돌려서 "지금 몇 점인지"와
"바꾸면 나아지는지"를 같이 봅니다. **재 보기 전에는 운영 기본값을 바꾸지
않습니다.**

겹말에 쓸 목소리는 `interference.wav`입니다. 같은 말뭉치의 **다른 문장**이라
대상의 원문에 없는 말입니다. 그래서 끼어든 말을 받아쓰면 CER이 올라갑니다.
파일이 없으면 겹말은 **재지 않습니다.** 조용히 건너뛰고 통과시키지 않습니다.

**같은 코드가 실행마다 다른 값을 냅니다.** 씨앗을 고정한 잡음에서도 소음 5dB가
13.4% ↔ 14.2%, 고정 파일인 겹말 0dB가 98.5% ↔ 116.4%였습니다. 그런데 **한 실행
안에서는** 세 번 받아써도 글자 하나까지 같고(`--repeat 3`, 폭 0), 디코더 난수를
고정해도(`--seed-decoder`) 차이 0입니다. 난수가 아닙니다. 남는 설명은 러너 CPU가
실행마다 달라 CTranslate2의 int8 커널이 다른 경로를 탄다는 것입니다. 그래서
첫 줄에 CPU 이름을 찍고, `--cpu-isa AVX2`로 명령어 집합을 고정해 봅니다
(`CT2_FORCE_CPU_ISA`). 다른 CPU에서 같은 값이 나오면 맞는 설명입니다.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from verify_transcribe import cer, squeeze

from pipeline.noise import Condition, conditions, gain_for_snr, limit_for, partial_window, worse
from pipeline.overlap import coverage, pick_speaker, speaker_spans
from worker.analysis import diarize, diarize_by_embedding, transcribe, transcribe_by_speaker

# 재 볼 후보 손잡이. 소음에서 휘파람처럼 같은 말을 되풀이하는 것은 앞 문장을
# 물고 가는 설정 탓이라고 알려져 있습니다. 정말 그런지는 이 검사가 답합니다.
CANDIDATE = {"condition_on_previous_text": False}


def run(command: list[str]) -> str:
    done = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if done.returncode:
        raise RuntimeError(f"{command[0]} 실패: {done.stderr.strip()[-400:]}")
    return done.stderr + done.stdout


def loudness(path: Path) -> float:
    """평균 음량(dBFS). 최댓값이 아니라 평균이어야 SNR이 맞습니다."""
    out = run(
        ["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"]
    )  # fmt: skip
    for line in out.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    raise RuntimeError(f"음량을 재지 못했습니다: {path}")


# 잡음 씨앗을 고정합니다. **고정하지 않으면 돌릴 때마다 다른 잡음이 깔려**
# 같은 코드에서도 값이 움직입니다(CI 실측: 소음 0dB가 23.1% → 20.9%, 소음 5dB가
# 17.2% → 14.2%). 그러면 회귀인지 잡음이 달라진 것인지 구분할 수 없습니다.
NOISE_SEED = 20260919

# 디코더 난수 씨앗. faster-whisper는 첫 시도가 미덥지 않으면 온도를 올려 다시
# 뽑는데(temperature fallback), 그때 표본을 **무작위로** 뽑습니다. 같은 소리에
# 답이 달라지는 원인으로 의심되는 곳입니다. 정말 그런지는 이 검사가 답합니다.
DECODER_SEED = 20260919


def seed_decoder(seed: int = DECODER_SEED) -> None:
    """디코더(ctranslate2)의 난수를 고정합니다. 받아쓰기 직전마다 부릅니다."""
    import ctranslate2

    ctranslate2.set_random_seed(seed)


def cpu_name() -> str:
    """이 기계의 CPU. 실행 사이에 값이 다를 때 가장 먼저 견줄 것입니다."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "알 수 없음"


def cpu_has(flag: str) -> bool:
    """CPU 플래그(avx2, avx512f 등)가 있는지. 없으면 False로 둡니다."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        if line.startswith("flags"):
            return flag in line.split(":", 1)[1].split()
    return False


def worst(values: list[float]) -> float:
    """여러 번 잰 것 중 가장 나쁜 값. 상한은 다음 실행이 우연히 넘지 않을 값이어야
    하므로 평균이 아니라 최댓값을 봅니다."""
    return max(values)


def spread(values: list[float]) -> float:
    """여러 번 잰 값의 폭(최대-최소). 이보다 작은 차이는 개선도 회귀도 아닙니다."""
    return max(values) - min(values)


def noise_file(path: Path, seconds: float) -> Path:
    """분홍 잡음. 흰 잡음보다 실제 방·거리 소리에 가깝습니다."""
    source = f"anoisesrc=color=pink:seed={NOISE_SEED}:duration={seconds:.2f}:sample_rate=16000"
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", source,
            "-ac", "1", "-c:a", "pcm_s16le", str(path),
        ]
    )  # fmt: skip
    return path


def fitted(source: Path, target: Path, seconds: float) -> Path:
    """끼어들 소리를 대상 길이에 맞춥니다. 짧으면 이어 붙이고 길면 자릅니다."""
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-stream_loop", "-1", "-i", str(source),
            "-t", f"{seconds:.2f}", "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le", str(target),
        ]
    )  # fmt: skip
    return target


def mixed(speech: Path, other: Path, gain_db: float, target: Path) -> Path:
    """정해진 이득으로 섞습니다. normalize=0이라야 대상 음량이 그대로입니다."""
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-i", str(speech), "-i", str(other),
            "-filter_complex",
            f"[1:a]volume={gain_db:.2f}dB[b];[0:a][b]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "[a]", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
        ]
    )  # fmt: skip
    return target


def seconds_of(path: Path) -> float:
    out = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]
    )  # fmt: skip
    return float(out.strip().splitlines()[-1])


def placed(source: Path, target: Path, *, at: float, total: float) -> Path:
    """소리를 `at`초부터 놓고 앞뒤를 무음으로 채워 `total`초로 만듭니다."""
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
            "-af", f"adelay={int(at * 1000)}:all=1,apad=whole_dur={total:.2f}",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
        ]
    )  # fmt: skip
    return target


def make(condition: Condition, sample: Path, interference: Path | None, work: Path) -> Path:
    """이 조건의 음성을 만듭니다."""
    if condition.kind == "clean":
        return sample
    span = seconds_of(sample)
    target = work / f"{condition.name}.wav"
    if condition.kind == "noise":
        other = fitted(noise_file(work / "pink.wav", span), work / "pink-fit.wav", span)
        gain = gain_for_snr(loudness(sample), loudness(other), condition.snr_db)
        return mixed(sample, other, gain, target)
    assert interference is not None  # conditions()가 없으면 넣지 않습니다.
    if condition.kind == "speech":
        other = fitted(interference, work / "voice-fit.wav", span)
        gain = gain_for_snr(loudness(sample), loudness(other), condition.snr_db)
        return mixed(sample, other, gain, target)
    # 부분 겹말. 이득은 **채우기 전** 조각으로 잽니다. 앞뒤 무음까지 평균에
    # 넣으면 조각이 작게 재어져 실제보다 크게 섞입니다.
    begin, finish = partial_window(span)
    piece = fitted(interference, work / "voice-piece.wav", finish - begin)
    gain = gain_for_snr(loudness(sample), loudness(piece), condition.snr_db)
    return mixed(
        sample, placed(piece, work / "voice-placed.wav", at=begin, total=span), gain, target
    )


def speaker_report(
    audio: Path,
    reference: str,
    target_spans: list[tuple[float, float]],
    truth: tuple[float, float] | None,
    *,
    token: str | None,
    model: str,
    language: str,
    seed: int | None = None,
) -> dict:
    """화자를 나눠 화자별로 받아쓰고, 우리가 아는 목소리의 자막만 채점합니다.

    돌려주는 것: 찾은 화자 수, 그 목소리의 자막 CER(전체 / 겹침 표시를 뺀 것),
    겹침 표시의 정밀도·재현율(부분 겹말에서만, 진짜 겹친 시각을 알 때).
    """
    try:
        turns = (
            diarize(audio, token=token, device="cpu", max_speakers=2)
            if token
            else diarize_by_embedding(audio, device="cpu", speakers=2)
        )
    except Exception as exc:  # noqa: BLE001 - 무엇이 막았는지 표에 남깁니다.
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    found = sorted({t.speaker for t in turns})
    who = pick_speaker(turns, target_spans)
    if len(found) < 2 or who is None:
        return {"speakers": len(found), "error": "화자를 둘로 가르지 못했습니다."}

    if seed is not None:
        seed_decoder(seed)
    spoken = transcribe_by_speaker(audio, turns, model=model, language=language, device="cpu")
    mine = [item for item in spoken if item.speaker == who]
    heard_all = " ".join(item.cue.text for item in mine)
    heard_clear = " ".join(item.cue.text for item in mine if not item.overlap)
    report = {
        "speakers": len(found),
        "who": who,
        "cues": len(mine),
        "flagged": sum(1 for item in mine if item.overlap),
        "cer_all": cer(reference, heard_all),
        "cer_clear": cer(reference, heard_clear),
        "heard": heard_all[:300],
    }
    if truth is not None:
        marked = [(item.cue.start, item.cue.end) for item in spoken if item.overlap]
        report["precision"], report["recall"] = coverage(marked, [truth])
        report["truth"] = truth
        report["spans"] = speaker_spans(turns, who)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ko")
    parser.add_argument(
        "--compare", action="store_true", help="후보 손잡이로 한 번 더 재서 견줍니다."
    )
    parser.add_argument(
        "--denoise",
        action="store_true",
        help="목소리만 분리(Demucs)한 뒤 전사해 한 번 더 견줍니다. 느립니다.",
    )
    parser.add_argument(
        "--by-speaker",
        action="store_true",
        help="겹말 조건에서 화자를 나눠 화자별로 받아쓰고 겹침 표시를 잽니다.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="조건마다 이만큼 받아써서 가장 나쁜 값과 폭(최대-최소)을 남깁니다.",
    )
    parser.add_argument(
        "--seed-decoder",
        action="store_true",
        help="디코더 난수를 고정한 설정을 나란히 재서 폭이 난수 탓인지 봅니다.",
    )
    parser.add_argument(
        "--cpu-isa",
        choices=["GENERIC", "AVX", "AVX2", "AVX512"],
        default=None,
        help="CTranslate2가 쓸 명령어 집합을 고정합니다(CT2_FORCE_CPU_ISA). "
        "러너 CPU가 달라도 같은 값이 나오는지 볼 때 씁니다.",
    )
    # 조건마다 상한이 다릅니다(pipeline.noise.MEASURED_CER, 실측 + 10%p).
    # 이 값을 주면 모든 조건에 같은 상한을 씁니다.
    parser.add_argument("--max-cer", type=float, default=None, help="모든 조건에 쓸 CER 상한")
    args = parser.parse_args()
    if args.cpu_isa:
        # 첫 모델을 싣기 전에 있어야 합니다. CTranslate2는 처음 쓸 때 한 번 읽습니다.
        os.environ["CT2_FORCE_CPU_ISA"] = args.cpu_isa

    directory = args.directory
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    reference = " ".join(item["text"] for item in expected["sentences"])
    sample = directory / "sample.wav"
    interference = directory / "interference.wav"
    has_speech = interference.is_file()

    isa = ", ".join(flag for flag in ("avx2", "avx512f") if cpu_has(flag)) or "avx 플래그 없음"
    forced = f", 명령어 집합 고정 {args.cpu_isa}" if args.cpu_isa else ""
    print(f"CPU {cpu_name()} ({isa}){forced}")
    print(f"모델 {args.model}, 음성 {sample} ({seconds_of(sample):.1f}초)")
    print(f"원문 {len(squeeze(reference))}자, 문장 {len(expected['sentences'])}개")
    if has_speech:
        print(f"겹말에 쓸 목소리 {interference} ({seconds_of(interference):.1f}초)")
    else:
        print("**겹말은 재지 않습니다.** interference.wav가 없습니다.")

    if args.repeat < 1:
        parser.error("--repeat는 1 이상이어야 합니다.")
    # (이름, 손잡이, 분리할지, 디코더 씨앗)
    settings: list[tuple[str, dict | None, bool, int | None]] = [("지금 설정", None, False, None)]
    if args.compare:
        settings.append(("손잡이", CANDIDATE, False, None))
        print(f"후보 손잡이: {CANDIDATE}")
    if args.denoise:
        settings.append(("분리 후", None, True, None))
        print("후보: 목소리만 분리한 뒤 전사 (겹말은 갈라지지 않습니다)")
    if args.seed_decoder:
        settings.append(("씨앗 고정", None, False, DECODER_SEED))
        print(f"후보: 디코더 난수 고정 (seed={DECODER_SEED})")
    if args.repeat > 1:
        print(f"조건마다 {args.repeat}번 받아씁니다. 표의 값은 가장 나쁜 것, 폭은 최대-최소입니다.")

    target_spans = [(float(item["start"]), float(item["end"])) for item in expected["sentences"]]
    token = os.environ.get("R4_HF_TOKEN")
    if args.by_speaker:
        print(f"화자 분리: {'pyannote' if token else 'embedding (토큰 없음)'}")

    # 조건마다 설정별 CER 값들. 한 번만 재면 길이 1입니다.
    rows: list[tuple[Condition, dict[str, list[float]]]] = []
    by_speaker: list[tuple[Condition, dict]] = []
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="robust-") as temp:
        work = Path(temp)
        for condition in conditions(with_speech=has_speech):
            audio = make(condition, sample, interference if has_speech else None, work)
            if args.by_speaker and condition.has_other_voice:
                by_speaker.append(
                    (
                        condition,
                        speaker_report(
                            audio,
                            reference,
                            target_spans,
                            partial_window(seconds_of(sample))
                            if condition.kind == "partial"
                            else None,
                            token=token,
                            model=args.model,
                            language=args.language,
                            seed=DECODER_SEED if args.seed_decoder else None,
                        ),
                    )
                )
            scores: dict[str, list[float]] = {}
            for label, tuning, denoise, seed in settings:
                heard_from = audio
                if denoise:
                    from worker.separation import separate_voice

                    heard_from = separate_voice(audio, work / f"{condition.name}-voice.wav")
                    heard_from = heard_from.background  # 고른 갈래가 담긴 파일입니다.
                scores[label] = []
                for attempt in range(args.repeat):
                    if seed is not None:
                        seed_decoder(seed)
                    cues = transcribe(
                        heard_from,
                        model=args.model,
                        language=args.language,
                        device="cpu",
                        tuning=tuning,
                    )
                    heard = " ".join(cue.text for cue in cues)
                    scores[label].append(cer(reference, heard))
                    # 무엇을 들었는지 함께 남깁니다. 숫자만으로는 되풀이인지
                    # 못 알아들은 것인지 구분할 수 없습니다.
                    where = f"{condition.label} / {label}"
                    if args.repeat > 1:
                        where += f" / {attempt + 1}회"
                    print(f"\n[{where}] 자막 {len(cues)}개, CER {scores[label][-1]:.1%}")
                    print(f"  {heard[:300] or '(없음)'}")
            rows.append((condition, scores))

    first = settings[0][0]
    baseline = rows[0][1]
    print("\n조건별 글자 오류율" + (" (가장 나쁜 값 / 폭)" if args.repeat > 1 else ""))
    header = "  {:<16}".format("조건")
    for label, *_ in settings:
        header += f"{label:>12}" + (f"{'폭':>7}" if args.repeat > 1 else "")
    print(header + f"{'원음 대비':>12}")
    for condition, scores in rows:
        line = f"  {condition.label:<16}"
        for label, *_ in settings:
            line += f"{worst(scores[label]):>11.1%}"
            if args.repeat > 1:
                line += f"{spread(scores[label]):>6.1%}"
        line += f"{worse(worst(baseline[first]), worst(scores[first])):>+11.1%}"
        print(line)
        limit = args.max_cer if args.max_cer is not None else limit_for(condition.name)
        if limit is not None and worst(scores[first]) > limit:
            problems.append(
                f"{condition.label}에서 CER {worst(scores[first]):.1%}가 "
                f"한계 {limit:.1%}를 넘습니다."
            )

    for label, *_ in settings[1:]:
        print(f"\n'{label}'가 조건마다 몇 점 바꿨는가 (가장 나쁜 값끼리, 음수가 좋아진 것)")
        for condition, scores in rows:
            print(f"  {condition.label:<16}{worst(scores[label]) - worst(scores[first]):>+11.1%}")
    if len(settings) > 1:
        print("\n**전체가 고르게 좋아질 때만 기본값을 바꿉니다.** 한 조건만 좋아진 것은")
        print("표본 하나에서 나온 우연일 수 있습니다.")
    if args.repeat > 1:
        widest = max(spread(scores[first]) for _, scores in rows)
        print(f"\n'{first}'의 가장 큰 폭: {widest:.1%}p. 이보다 작은 차이는 개선이 아닙니다.")

    if by_speaker:
        print("\n화자별 전사 (겹말 조건만). 우리가 아는 목소리의 자막만 채점합니다.")
        print("  '겹침 뺀 것'은 겹침 표시가 붙은 자막을 버리고 잰 값입니다.")
        for condition, report in by_speaker:
            plain = worst(next(scores for row, scores in rows if row is condition)[first])
            if "error" in report:
                count = report.get("speakers", "?")
                print(f"  {condition.label:<16} 화자 {count}명 — {report['error']}")
                continue
            line = (
                f"  {condition.label:<16} 화자 {report['speakers']}명, 자막 {report['cues']}개"
                f"(겹침 표시 {report['flagged']}개)  섞어서 {plain:.1%} → "
                f"화자별 {report['cer_all']:.1%} / 겹침 뺀 것 {report['cer_clear']:.1%}"
            )
            if "precision" in report:
                line += f"  표시 정밀도 {report['precision']:.0%} 재현율 {report['recall']:.0%}"
            print(line)
            print(f"      {report['heard'] or '(없음)'}")
        print("\n**겹친 시간의 자막은 여전히 못 믿습니다.** 이 방법은 겹치지 않은 시간을")
        print("살리고 겹친 시간에 표시를 붙이는 것까지입니다.")

    if not has_speech:
        print("\n겹말은 재지 못했습니다.")
        print("fetch_korean_speech.py --interference로 목소리를 받으세요.")
    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n이 숫자는 표본 하나에서 나온 것입니다. 데이터셋 행이 바뀌면 값도 움직입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
