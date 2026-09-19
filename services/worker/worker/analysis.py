"""Optional open-source analysis providers, loaded only when explicitly requested."""

from __future__ import annotations

import inspect
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pipeline.alignment import (
    WordTiming,
    cues_for_lines,
    merge_spans,
    snap_starts,
    spans_from_timestamps,
    supported_options,
)
from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn, cluster, turns_from_labels, windows
from pipeline.subtitle_files import dump_subtitles, parse_subtitles
from worker.rendering import ffmpeg_binary

# getattr 기본값. 속성 이름이 버전마다 달라도 "없음"과 "None"을 구분합니다.
_PRESENT = object()


class MissingDependency(RuntimeError):
    """선택 의존성이 없습니다. 설치 안내는 외부 입력이 아니므로 그대로 보여줍니다."""


def transcribe(
    source: Path, *, model: str = "small", language: str | None = None, device: str = "cpu"
) -> list[Cue]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise MissingDependency(
            "STT 의존성이 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    engine = WhisperModel(
        model, device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    segments, _ = engine.transcribe(
        str(source), language=language, vad_filter=True, word_timestamps=True
    )
    return [
        Cue(start=s.start, end=s.end, text=s.text.strip())
        for s in segments
        if s.text.strip() and s.end > s.start
    ]


def align_text(
    source: Path,
    text: str,
    *,
    model: str = "small",
    language: str | None = None,
    device: str = "cpu",
) -> list[Cue]:
    """이미 있는 대본을 오디오에 맞춰 시각을 붙입니다.

    전사가 아니라 정렬입니다. 글자는 입력한 그대로 두고 시간만 찾습니다.
    사용자가 손으로 고친 대본이나 타이밍 없이 받은 대본에 씁니다.

    대본에 줄바꿈이 있으면 그 줄이 자막 하나가 됩니다. 정렬기의 줄 유지
    옵션은 시각을 밀어서(측정: 첫 자막 1초 지연) 쓰지 않습니다. 대신 한
    덩어리로 정렬해 정확한 단어 시각을 받고 줄 나누기는 우리가 합니다.
    맞출 수 없으면 정렬기가 나눈 구간을 그대로 씁니다.
    """
    if not text.strip():
        raise ValueError("정렬할 대본이 비어 있습니다.")
    try:
        import stable_whisper
    except ImportError as exc:
        raise MissingDependency(
            "자막 정렬 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc
    engine = stable_whisper.load_faster_whisper(
        model, device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    result = engine.align(str(source), text, language=language)
    cues = cues_for_lines(text.splitlines(), word_timings(result)) or [
        Cue(start=s.start, end=s.end, text=s.text.strip())
        for s in result.segments
        if s.text.strip() and s.end > s.start
    ]
    # 단어 시각이 무음 안쪽으로 당겨지거나 발화 중간으로 밀리는 경우가 있어
    # 자막 시작을 그 자막이 걸친 발화의 시작에 맞춥니다.
    cues = snap_starts(cues, speech_spans(source))
    if not cues:
        raise RuntimeError("대본을 오디오에 맞추지 못했습니다. 언어와 음성을 확인하세요.")
    return cues


_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")


# VAD 기본값은 자막 시작을 맞추는 데 두 가지가 어긋납니다.
#
# - speech_pad_ms=400: 발화 앞뒤에 여유를 붙여서 자막이 그만큼 일찍
#   시작합니다(측정: 첫 자막 0.59초, 실제 1.00초).
# - min_silence_duration_ms=2000: 2초보다 짧은 무음은 발화를 끊지 않습니다.
#   문장 사이를 1초 쉬는 말은 통째로 한 구간이 되고(측정: 18초 음성 전체가
#   발화 구간 1개), 그러면 맞출 시작점이 없어 자막이 그대로 밀립니다.
#
# 무음 기준을 짧게 두면 문장 안에서도 잘게 끊깁니다. 그 조각을 다시 합치는
# 일은 merge_spans가 합니다. 잘게 받아서 우리가 합치는 편이, 공급자 기본값에
# 맡기고 왜 안 끊겼는지 뒤늦게 재는 것보다 낫습니다.
_VAD_SETTINGS = {"speech_pad_ms": 0, "min_silence_duration_ms": 200}


def vad_spans(source: Path) -> list[tuple[float, float]]:
    """Silero VAD로 발화 구간을 찾습니다. 못 쓰면 빈 목록입니다.

    faster-whisper에 들어 있는 VAD라 새 의존성이 없습니다. 실제 녹음은
    배경 잡음이 있어서 무음 감지(FFmpeg silencedetect)로는 발화 구간을
    찾지 못합니다(측정: 사람 목소리에서 자막이 1.57초 늦게 시작). VAD는
    잡음이 있어도 사람 목소리를 찾습니다.
    """
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return []
    try:
        audio = decode_audio(str(source), sampling_rate=16000)
        options = supported_options(VadOptions, _VAD_SETTINGS)
        stamps = get_speech_timestamps(audio, VadOptions(**options))
    except Exception:  # noqa: BLE001 - 다듬기 실패가 정렬을 막지 않습니다.
        return []
    return spans_from_timestamps(stamps)


def silence_spans(
    source: Path, *, noise: str = "-35dB", minimum: float = 0.25
) -> list[tuple[float, float]]:
    """무음 사이를 발화 구간으로 봅니다. VAD를 못 쓸 때의 대안입니다.

    디지털 무음이 또렷한 음성에서만 믿을 만합니다. FFmpeg가 없거나 실패하면
    빈 목록입니다.
    """
    try:
        binary = ffmpeg_binary()
    except Exception:  # noqa: BLE001 - FFmpeg가 없으면 다듬지 않고 넘어갑니다.
        return []
    try:
        done = subprocess.run(
            [
                binary,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-af",
                f"silencedetect=noise={noise}:duration={minimum}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    starts = [float(v) for v in _SILENCE_START.findall(done.stderr)]
    ends = [float(v) for v in _SILENCE_END.findall(done.stderr)]
    # 무음이 끝나는 지점부터 다음 무음이 시작되는 지점까지가 발화입니다.
    begins = ([] if starts and starts[0] <= 0.01 else [0.0]) + ends
    finishes = starts[1:] if starts and starts[0] <= 0.01 else starts
    return [(b, f) for b, f in zip(begins, finishes, strict=False) if f > b]


def speech_spans(source: Path) -> list[tuple[float, float]]:
    """발화 구간 목록. VAD를 먼저 쓰고 안 되면 무음 감지로 내려갑니다."""
    found = vad_spans(source)
    return found if found else silence_spans(source)


# 목소리 특징을 뽑는 공개 모델. 약관 동의도 토큰도 필요 없습니다.
_EMBEDDING_MODEL = "speechbrain/spkrec-ecapa-voxceleb"


def diarize_by_embedding(
    source: Path,
    *,
    device: str = "cpu",
    speakers: int = 2,
    model: str = _EMBEDDING_MODEL,
) -> list[SpeakerTurn]:
    """토큰 없이 도는 화자 분리. 발화 구간을 잘라 목소리끼리 묶습니다.

    pyannote는 게이트 모델이라 토큰이 있어야 합니다. 토큰이 없는 환경에서도
    화자를 나눌 수 있게, 공개 목소리 특징 모델과 우리 묶기 규칙으로 같은 일을
    합니다. 발화 구간은 이미 쓰고 있는 VAD가 찾고, 그 구간을 겹치는 창으로
    잘라 창마다 특징을 뽑은 뒤 코사인 거리로 묶습니다.

    **품질은 pyannote와 다릅니다.** 겹쳐 말하는 구간을 다루지 못하고, 화자
    수를 스스로 세지 않아 `speakers`로 알려 줘야 합니다. 목소리가 비슷하면
    갈리지 않습니다. 그래서 기본 공급자가 아니라 선택지입니다.
    """
    if speakers < 1:
        raise ValueError("화자 수는 1 이상이어야 합니다.")
    try:
        import torch
        from faster_whisper.audio import decode_audio
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise MissingDependency(
            "목소리 특징 모델 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc

    audio = decode_audio(str(source), sampling_rate=16000)
    spans = merge_spans(speech_spans(source))
    cut = windows(spans)
    if not cut:
        raise RuntimeError("발화 구간을 찾지 못했습니다. 음성이 있는 원본인지 확인하세요.")

    encoder = EncoderClassifier.from_hparams(source=model, run_opts={"device": device})
    vectors: list[list[float]] = []
    kept: list[tuple[float, float]] = []
    for begin, finish in cut:
        piece = audio[int(begin * 16000) : int(finish * 16000)]
        # 너무 짧은 조각은 특징이 불안정합니다. 묶기를 흔들기보다 버립니다.
        if len(piece) < 16000 // 2:
            continue
        with torch.no_grad():
            found = encoder.encode_batch(torch.tensor(piece).unsqueeze(0))
        vectors.append(found.squeeze().tolist())
        kept.append((begin, finish))
    if not vectors:
        raise RuntimeError("특징을 뽑을 만큼 긴 발화가 없습니다.")

    turns = turns_from_labels(kept, cluster(vectors, min(speakers, len(vectors))))
    if not turns:
        raise RuntimeError("화자를 찾지 못했습니다. 음성이 있는 원본인지 확인하세요.")
    return turns


# 약관 동의가 필요한 페이지. 토큰만 있고 동의가 빠지면 같은 증상이 납니다.
# 어느 모델을 쓰는지는 버전이 정합니다(측정: 설치된 버전은
# speaker-diarization-community-1을 받으러 갑니다). 그래서 실제 쓰는 모델을
# 찾아 맨 앞에 넣고, 아래는 흔히 함께 필요한 것들입니다.
GATED_PAGES = (
    "https://huggingface.co/pyannote/speaker-diarization-3.1",
    "https://huggingface.co/pyannote/segmentation-3.0",
)


def diarization_arguments(factory, *, token: str, device: str) -> dict:  # noqa: ANN001
    """이 whisperx 버전이 받는 이름으로 토큰과 장치를 넘깁니다.

    인자 이름이 버전마다 바뀝니다(측정: 설치된 버전은 `use_auth_token`을 받지
    않아 화자 분리가 아예 시작되지 못했습니다). 이름을 고정해 두면 다음
    버전에서 같은 일이 또 납니다. 받는 이름만 골라 넣습니다.
    """
    options = supported_options(
        factory, {"token": token, "use_auth_token": token, "device": device}
    )
    # 둘 다 받는 버전이면 하나만 넣습니다. 같은 값을 두 번 넘기지 않습니다.
    if "token" in options:
        options.pop("use_auth_token", None)
    if not options.get("token") and not options.get("use_auth_token"):
        raise MissingDependency(
            "이 whisperx 버전에 토큰을 넘길 자리가 없습니다. 받는 인자: "
            + ", ".join(sorted(inspect.signature(factory).parameters))
        )
    return options


def default_model_name(factory) -> str | None:  # noqa: ANN001
    """이 버전이 기본으로 쓰는 모델 이름. 약관 동의는 그 모델 페이지에서 합니다."""
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return None
    for name in ("model_name", "model", "checkpoint"):
        found = parameters.get(name)
        if found is not None and isinstance(found.default, str):
            return found.default
    return None


def repository_in(detail: str) -> str | None:
    """실패한 이야기에 적힌 pyannote 저장소 이름. 없으면 None."""
    found = re.search(r"pyannote/[A-Za-z0-9._-]+", detail)
    return found.group(0) if found else None


def gated_hint(detail: str, model: str | None = None) -> str:
    """모델을 못 불러왔을 때 사람이 고칠 수 있는 말로 바꿉니다.

    pyannote는 접근이 막히면 예외 대신 빈 모델을 돌려주기도 합니다. 그러면
    한참 뒤에 엉뚱한 AttributeError로 터져서 무엇이 잘못됐는지 알 수 없습니다.
    토큰이 있어도 두 페이지 중 하나라도 동의가 빠지면 같은 증상이 나므로,
    둘 다 짚어 줍니다.

    쓰는 모델 이름을 함수 서명에서 못 찾을 때가 있습니다(측정: 설치된
    whisperx는 None입니다). 그럴 때는 실패한 이야기 자체에서 찾습니다.
    거기에는 막힌 저장소 이름이 적혀 있습니다. 엉뚱한 페이지를 짚어 주면
    사람이 동의를 다 해 놓고도 같은 오류를 다시 봅니다.
    """
    pages = list(GATED_PAGES)
    model = model or repository_in(detail)
    if model and all(model not in page for page in pages):
        # 버전마다 기본 모델이 다릅니다. 쓰는 모델의 페이지에서 동의해야 합니다.
        pages.insert(0, f"https://huggingface.co/{model}")
    listed = "\n".join(f"  {page}" for page in pages)
    return (
        "pyannote 모델을 불러오지 못했습니다. 토큰이 있어도 약관 동의가 빠지면 같은 "
        f"증상이 납니다. 아래 페이지 모두에서 동의했는지 확인하세요:\n{listed}\n"
        f"원래 증상: {detail}"
    )


def diarize(
    source: Path,
    *,
    token: str | None,
    device: str = "cpu",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[SpeakerTurn]:
    """누가 언제 말했는지 구간으로 나눕니다. 무엇을 말했는지는 다루지 않습니다.

    pyannote 모델이 Hugging Face 게이트 모델이라 토큰과 약관 동의가 필요합니다.
    토큰이 없으면 호출 전에 막습니다. 모델은 첫 실행 때 내려받습니다.
    토큰 없이 쓰려면 `diarize_by_embedding()`이 있습니다. 품질이 다릅니다.
    """
    if not token:
        raise MissingDependency(
            "화자 분리에는 Hugging Face 토큰이 필요합니다. pyannote 모델 약관에 동의한 뒤 "
            "R4_HF_TOKEN을 설정하세요."
        )
    try:
        # whisperx 버전에 따라 위치가 다릅니다. 둘 다 받아 줍니다.
        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError:
            from whisperx import DiarizationPipeline
    except ImportError as exc:
        raise MissingDependency(
            "화자 분리 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc
    model = default_model_name(DiarizationPipeline)
    arguments = diarization_arguments(DiarizationPipeline, token=token, device=device)
    try:
        pipeline = DiarizationPipeline(**arguments)
    except TypeError as exc:
        # 인자 이름이 아니라 개수나 형이 맞지 않는 경우입니다. 약관 문제가
        # 아니므로 그렇게 말하지 않습니다.
        raise MissingDependency(
            f"whisperx 화자 분리 진입점과 호출이 맞지 않습니다: {exc}. "
            "pyannote.audio와 whisperx 버전을 확인하세요."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 고칠 수 있는 말로 바꿉니다.
        raise MissingDependency(gated_hint(f"{type(exc).__name__}: {exc}", model)) from exc
    # 접근이 막히면 예외 없이 빈 모델이 돌아오기도 합니다. 여기서 잡지 않으면
    # 다음 줄에서 AttributeError로 터지고 원인이 보이지 않습니다.
    inner = getattr(pipeline, "model", _PRESENT)
    if pipeline is None or inner is None:
        raise MissingDependency(
            gated_hint("모델이 비어 있습니다(pyannote가 None을 돌려줬습니다).", model)
        )
    frame = pipeline(str(source), min_speakers=min_speakers, max_speakers=max_speakers)
    turns = [
        SpeakerTurn(start=float(row.start), end=float(row.end), speaker=str(row.speaker))
        for row in frame.itertuples()
        if float(row.end) > float(row.start)
    ]
    if not turns:
        raise RuntimeError("화자를 찾지 못했습니다. 음성이 있는 원본인지 확인하세요.")
    return sorted(turns, key=lambda t: t.start)


def word_timings(result) -> list[WordTiming]:  # noqa: ANN001
    """정렬 결과에서 단어 시각을 모읍니다. 단어가 없으면 빈 목록입니다."""
    found: list[WordTiming] = []
    for segment in getattr(result, "segments", []):
        for word in getattr(segment, "words", None) or []:
            text = getattr(word, "word", "") or ""
            start, end = getattr(word, "start", None), getattr(word, "end", None)
            if text.strip() and start is not None and end is not None:
                found.append(WordTiming(start=float(start), end=float(end), text=text))
    return found


def detect_scenes(source: Path, *, threshold: float = 27.0) -> list[dict]:
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise MissingDependency(
            "장면 감지 의존성이 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    return [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in detect(
            str(source), ContentDetector(threshold=threshold), start_in_scene=True
        )
    ]


# ffsubsync가 받는 발화 검출기 이름. 목록에 없는 값을 넘기면 argparse가 그
# 자리에서 프로세스를 끝냅니다(워커가 죽습니다). 그래서 넘기기 전에 봅니다.
SYNC_VADS = (
    "webrtc",
    "auditok",
    "silero",
    "subs_then_webrtc",
    "subs_then_auditok",
    "subs_then_silero",
)


@dataclass(frozen=True, slots=True)
class SyncOptions:
    """싱크 보정기에 넘기는 설정. 기본값의 근거는 docs/TECH_DECISIONS.md입니다."""

    fix_framerate: bool = False
    max_offset_seconds: float = 10.0
    vad: str | None = None

    def arguments(self) -> list[str]:
        if self.max_offset_seconds <= 0:
            raise ValueError("이동 상한은 0보다 커야 합니다.")
        if self.vad and self.vad not in SYNC_VADS:
            raise ValueError(
                f"모르는 발화 검출기입니다: {self.vad}. 쓸 수 있는 값: {', '.join(SYNC_VADS)}"
            )
        extra: list[str] = []
        if not self.fix_framerate:
            extra.append("--no-fix-framerate")
        extra += ["--max-offset-seconds", str(self.max_offset_seconds)]
        if self.vad:
            extra += ["--vad", self.vad]
        return extra


def _run_sync(args):  # noqa: ANN001 - ffsubsync의 argparse.Namespace입니다.
    """보정기를 실제로 돌립니다. 시험에서 이 자리를 갈아끼워 응답을 꾸밉니다."""
    from ffsubsync.ffsubsync import run

    return run(args)


def sync_subtitles(
    source: Path, cues: list[Cue], options: SyncOptions | None = None
) -> tuple[list[Cue], dict]:
    """이미 있는 자막의 시각을 원본 음성에 맞춰 통째로 옮깁니다(ffsubsync).

    **글자는 건드리지 않습니다.** 돌아온 파일에서 시각만 가져와 원래 자막에
    붙입니다. 보정기는 자막을 다시 쓸 수 있지만 대본은 사람이 정한 것입니다.

    **보정기의 성공 표시는 믿을 게 못 됩니다.** ffsubsync는 정렬 점수가 음수일
    때만 `sync_was_successful=False`로 표시합니다(`ffsubsync.py`의 `best_score < 0`).
    즉 터무니없는 값을 자신 있게 돌려줘도 성공이라고 합니다. 실제로 사람 목소리
    34초 표본에서 -23.25초를 성공으로 내놓은 적이 있습니다. 그래서 여기서 따로
    봅니다.

    - 자막을 원본 시작 앞으로 밀어내는 보정은 받지 않습니다. 대본은 이 원본에서
      나왔으므로 그런 이동은 맞을 수 없습니다.
    - 자막 개수가 달라지면 시각을 원래 자막에 도로 맞출 수 없으므로 실패입니다.

    얼마나 옮겼는지(`offset_seconds`)를 함께 돌려줍니다. 사람이 그 값을 보고
    쓸지 말지 정합니다.
    """
    if not cues:
        raise ValueError("보정할 자막이 없습니다.")
    options = options or SyncOptions()
    try:
        from ffsubsync.ffsubsync import make_parser
    except ImportError as exc:
        raise MissingDependency(
            "자막 싱크 보정 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="r4-sync-") as directory:
        temp = Path(directory)
        before, after = temp / "in.srt", temp / "out.srt"
        before.write_text(dump_subtitles(cues), encoding="utf-8")
        parser = make_parser()
        report = _run_sync(
            parser.parse_args(
                [str(source), "-i", str(before), "-o", str(after), *options.arguments()]
            )
        )
        if report.get("retval") or not report.get("sync_was_successful", True):
            raise ValueError("자막을 음성에 맞추지 못했습니다. 원본과 자막이 맞는지 확인하세요.")
        shift = float(report.get("offset_seconds", 0.0))
        earliest = min(cue.start for cue in cues)
        # 원본 앞으로 밀려난 자막은 파일에서 아예 사라집니다. 그러면 개수가 달라
        # "개수가 다르다"는 말만 남고 무엇이 잘못됐는지는 안 보입니다.
        if earliest + shift < 0:
            raise ValueError(
                f"보정값 {shift:+.3f}초는 자막을 원본 시작 앞으로 밀어냅니다. 쓰지 않습니다."
            )
        moved, _ = parse_subtitles(after.read_text(encoding="utf-8"))

    if len(moved) != len(cues):
        raise ValueError("보정 결과의 자막 개수가 달라 시각을 맞출 수 없습니다.")
    shifted = [
        Cue(start=new.start, end=new.end, text=old.text)
        for old, new in zip(cues, moved, strict=True)
    ]
    return shifted, {
        "offset_seconds": round(shift, 3),
        "framerate_scale": round(float(report.get("framerate_scale_factor", 1.0)), 6),
        "vad": options.vad or "",
        "max_offset_seconds": options.max_offset_seconds,
    }
