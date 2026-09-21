"""Opt-in provider adapters. Callers must reserve budget before paid calls.

No adapter is invoked automatically by the free/local media worker. Inject clients
for contract tests. Persist returned remote ids before polling or retry decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx


class ProviderError(RuntimeError):
    pass


def require_paid(enabled: bool) -> None:
    if not enabled:
        raise ProviderError(
            "유료 호출이 비활성화되어 있습니다. 예산 예약 후 명시적으로 활성화하세요."
        )


def video_terms(original: str, translated: str, source: str | None, target: str) -> str:
    """Resolve only explicit video recording, never ambiguous or mixed audio/video cues."""
    if target.split("-")[0] != "zh":
        return translated
    explicit = {"ko": ("녹화", "녹음"), "ja": ("録画", "録音")}.get(source)
    if explicit and explicit[0] in original and explicit[1] not in original:
        return translated.replace("录音", "录像").replace("錄音", "錄影")
    return translated


class GoogleTranslator:
    def __init__(self, project: str, *, client=None, allow_paid: bool = False):
        self.project, self.client, self.allow_paid = project, client, allow_paid

    def translate(self, texts: list[str], target: str, source: str | None = None) -> list[str]:
        require_paid(self.allow_paid)
        if not texts or sum(map(len, texts)) > 25000:
            raise ValueError("번역 배치는 비어 있지 않고 25,000자 이하여야 합니다.")
        if self.client is None:
            from google.cloud import translate_v3

            self.client = translate_v3.TranslationServiceClient()
        request = {
            "parent": f"projects/{self.project}/locations/global",
            "contents": texts,
            "target_language_code": target,
            "mime_type": "text/plain",
        }
        if source:
            request["source_language_code"] = source
        # Disable SDK automatic retries: the caller owns budget and retry policy.
        response = self.client.translate_text(request=request, retry=None, timeout=60)
        output = [item.translated_text for item in response.translations]
        if len(output) != len(texts):
            raise ProviderError("번역 응답 수가 입력과 다릅니다.")
        return [
            video_terms(original, translated, source, target)
            for original, translated in zip(texts, output, strict=True)
        ]


class DeepLTranslator:
    """DeepL API v2. Google과 같은 모양(texts → texts)이라 번역 단계가 골라 씁니다.

    공식 SDK 대신 HTTP를 직접 부릅니다. 의존성을 하나 덜고, 시험이 `client`에
    대역을 넣기 쉽습니다. 무료 키는 api-free.deepl.com, 유료 키는 api.deepl.com입니다.
    """

    def __init__(self, api_key: str, *, client: httpx.Client, allow_paid: bool = False):
        self.api_key, self.client, self.allow_paid = api_key, client, allow_paid
        host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
        self.url = f"https://{host}/v2/translate"

    def translate(self, texts: list[str], target: str, source: str | None = None) -> list[str]:
        from pipeline.languages import DEEPL_SOURCES, DEEPL_TARGETS, provider_code

        require_paid(self.allow_paid)
        if not texts or len(texts) > 50 or sum(map(len, texts)) > 25000:
            raise ValueError("DeepL 배치는 1~50문장, 25,000자 이하여야 합니다.")
        body = {
            "text": texts,
            "target_lang": provider_code(DEEPL_TARGETS, target, "DeepL"),
            # 자막 한 줄이 한 문장이 아닐 수 있습니다. 줄을 문장으로 다시 자르지 않게 합니다.
            "split_sentences": "0",
            "preserve_formatting": True,
        }
        if source:
            body["source_lang"] = provider_code(DEEPL_SOURCES, source, "DeepL")
        response = self.client.post(
            self.url,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
            json=body,
            timeout=60,
        )
        if response.status_code != 200:
            raise ProviderError(f"DeepL 번역 실패: HTTP {response.status_code}")
        output = [item["text"] for item in response.json().get("translations", [])]
        if len(output) != len(texts):
            raise ProviderError("DeepL 응답 수가 입력과 다릅니다.")
        return [
            video_terms(original, translated, source, target)
            for original, translated in zip(texts, output, strict=True)
        ]


class HuggingFaceTranslator:
    """로컬 번역 모델(NLLB-200). 유료 호출이 아니라 예산 예약 없이 돕니다.

    `pipeline`에 transformers 파이프라인(또는 대역)을 넣습니다. 비어 있으면 모델을
    내려받아 만듭니다(첫 실행에 수 GB, CPU에서 느립니다). 출발 언어를 모르면
    쓸 수 없습니다. NLLB는 출발 언어 코드를 요구합니다.
    """

    DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"

    def __init__(self, model: str = DEFAULT_MODEL, *, pipeline=None, device: str = "cpu"):
        self.model, self.pipeline, self.device = model, pipeline, device

    def translate(self, texts: list[str], target: str, source: str | None = None) -> list[str]:
        from pipeline.languages import NLLB_CODES, provider_code

        if not texts:
            raise ValueError("번역할 문장이 없습니다.")
        if not source:
            raise ValueError("로컬 번역 모델은 출발 언어를 알아야 합니다. 원본 언어를 지정하세요.")
        src = provider_code(NLLB_CODES, source, "NLLB")
        tgt = provider_code(NLLB_CODES, target, "NLLB")
        if self.pipeline is None:
            from transformers import pipeline as make_pipeline

            self.pipeline = make_pipeline("translation", model=self.model, device=self.device)
        rows = self.pipeline(texts, src_lang=src, tgt_lang=tgt, max_length=512)
        output = [row["translation_text"] for row in rows]
        if len(output) != len(texts):
            raise ProviderError("로컬 번역 모델 응답 수가 입력과 다릅니다.")
        return output


# 문맥·말투 보정과 직접 번역에 쓰는 모델. 줄 수가 많고 답이 짧아 빠른 모델을 씁니다.
TRANSLATE_MODEL = "claude-sonnet-5"
TRANSLATE_MAX_TOKENS = 16000
# 프롬프트가 바뀌면 이 값을 올립니다. 번역 기억의 키에 들어가 옛 답을 다시 쓰지 않게 합니다.
TRANSLATE_PROMPT_VERSION = "1"

TRANSLATE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "입력 줄 번호(#n)"},
                        "text": {"type": "string", "description": "그 줄의 번역"},
                    },
                    "required": ["id", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["lines"],
        "additionalProperties": False,
    },
}

# 규칙 문구는 LLM-Subtrans(instructions.txt, MIT)와 srt-ai의 1:1 규칙을 참고했습니다.
TRANSLATE_SYSTEM = """You translate subtitle lines for short-form video.

You receive numbered lines (#n<tab>text) to translate, optionally with [CONTEXT] lines
before and after them. Read the context to understand the conversation, but translate
ONLY the numbered lines.

CRITICAL RULES:
1. Output EXACTLY one translation per numbered line, with the same id. Never merge or
   split lines; when one sentence spans several lines, translate each fragment under its own id.
2. Keep the meaning, register and tone of the source. Do not add or drop information.
3. Follow the glossary rules exactly. Keep names and numbers as they are.
4. Subtitles are read quickly: prefer short, natural phrasing in the target language.
5. Do not ask questions or add commentary."""

REFINE_SYSTEM = """You polish machine-translated subtitle lines for short-form video.

You receive numbered lines: the source text and a draft translation (#n<tab>source<tab>draft),
with [CONTEXT] lines before and after. Fix what the draft got wrong: mistranslations, wrong
register or tone for the speaker, awkward phrasing, terminology that ignores the glossary.
Keep drafts that are already fine — do not rewrite for style alone.

CRITICAL RULES:
1. Output EXACTLY one line per id. Never merge or split lines.
2. Keep names and numbers exactly as in the source. Follow the glossary rules exactly.
3. Keep it short: subtitles are read quickly.
4. Do not ask questions or add commentary."""

RETRY_INSTRUCTIONS = (
    "The previous answer was rejected: {reason}. Answer again with exactly one line per id, "
    "ids {ids}, and nothing else."
)


class ClaudeTranslator:
    """Claude로 묶음을 번역하거나(모드 translate) 기계 번역 초안을 보정합니다(모드 refine).

    입력은 `pipeline.translation_jobs.TranslationJob`입니다. 답은 번호 → 번역문이고,
    번호가 빠지거나 남으면 한 번 더 묻습니다(LLM-Subtrans의 retry_instructions).
    그래도 틀리면 ProviderError입니다. 절반씩 나눠 다시 묻는 것은 하지 않습니다.
    한 묶음이 실패하면 그 묶음만 단계 재실행으로 다시 갑니다.
    """

    def __init__(self, *, client=None, allow_paid: bool = False, model: str = TRANSLATE_MODEL):
        self.client, self.allow_paid, self.model = client, allow_paid, model

    def translate(self, job, *, drafts: list[str] | None = None) -> list[str]:
        require_paid(self.allow_paid)
        if not job.translate:
            raise ValueError("번역할 줄이 없습니다.")
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        system = REFINE_SYSTEM if drafts is not None else TRANSLATE_SYSTEM
        content = job.prompt(drafts=drafts)
        rejected = None
        for _attempt in range(2):
            if rejected:
                content = RETRY_INSTRUCTIONS.format(reason=rejected, ids=job.ids) + "\n\n" + content
            response = self.client.messages.create(
                model=self.model,
                max_tokens=TRANSLATE_MAX_TOKENS,
                system=system,
                output_config={"format": TRANSLATE_SCHEMA},
                messages=[{"role": "user", "content": content}],
            )
            stop = getattr(response, "stop_reason", None)
            if stop == "refusal":
                raise ProviderError("모델이 답을 거절했습니다.")
            if stop == "max_tokens":
                raise ProviderError("답이 잘렸습니다. 묶음을 줄이세요.")
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                rows = json.loads(text)["lines"]
                answer = {int(row["id"]): str(row["text"]) for row in rows}
            except (ValueError, KeyError, TypeError) as exc:
                rejected = f"unreadable answer ({exc})"
                continue
            missing = [i for i in job.ids if i not in answer or not answer[i].strip()]
            extra = [i for i in answer if i not in job.ids]
            if missing or extra:
                rejected = f"missing ids {missing}, unexpected ids {extra}"
                continue
            return [answer[i] for i in job.ids]
        raise ProviderError(f"번역 답이 두 번 모두 맞지 않았습니다: {rejected}")


class ElevenLabsSpeech:
    def __init__(self, api_key: str, *, client: httpx.Client, allow_paid: bool = False):
        self.api_key, self.client, self.allow_paid = api_key, client, allow_paid

    def synthesize(
        self, text: str, voice_id: str, destination: Path, *, model: str = "eleven_multilingual_v2"
    ) -> str | None:
        require_paid(self.allow_paid)
        if not text.strip() or len(text) > 5000 or not voice_id:
            raise ValueError("음성과 1~5,000자의 대본이 필요합니다.")
        response = self.client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe='')}",
            headers={"xi-api-key": self.api_key},
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": model},
            timeout=120,
        )
        if response.status_code != 200 or not response.content:
            raise ProviderError(f"더빙 요청 실패: HTTP {response.status_code}")
        destination.write_bytes(response.content)
        return response.headers.get("request-id")


class SyncLipsync:
    def __init__(self, api_key: str, *, client: httpx.Client, allow_paid: bool = False):
        self.api_key, self.client, self.allow_paid = api_key, client, allow_paid

    def submit(self, video_url: str, audio_url: str, *, model: str = "lipsync-2") -> str:
        require_paid(self.allow_paid)
        for url in (video_url, audio_url):
            if urlparse(url).scheme != "https":
                raise ValueError("립싱크 입력은 공급자가 접근 가능한 HTTPS URL이어야 합니다.")
        response = self.client.post(
            "https://api.sync.so/v2/generate",
            headers={"x-api-key": self.api_key},
            timeout=60,
            json={
                "model": model,
                "input": [{"type": "video", "url": video_url}, {"type": "audio", "url": audio_url}],
            },
        )
        if response.status_code not in (200, 201):
            raise ProviderError(f"립싱크 요청 실패: HTTP {response.status_code}")
        remote_id = response.json().get("id")
        if not isinstance(remote_id, str) or not remote_id:
            raise ProviderError("립싱크 작업 ID가 없습니다. 자동 재제출하지 마세요.")
        return remote_id

    def status(self, remote_id: str) -> dict:
        response = self.client.get(
            f"https://api.sync.so/v2/generate/{quote(remote_id, safe='')}",
            headers={"x-api-key": self.api_key},
            timeout=30,
        )
        if response.status_code != 200:
            raise ProviderError(f"립싱크 조회 실패: HTTP {response.status_code}")
        data = response.json()
        return {key: data.get(key) for key in ("id", "status", "outputUrl", "error")}


# 하이라이트 추천에 쓰는 모델. 대본 전체를 한 번에 읽고 무엇이 재미있는지
# 판단하는 일이라 가장 좋은 것을 씁니다. 바꾸려면 여기 한 줄입니다.
HIGHLIGHT_MODEL = "claude-opus-5"
# 답은 후보 몇 개뿐이라 길지 않습니다. 생각까지 여유를 둔 값입니다.
HIGHLIGHT_MAX_TOKENS = 8000

# 시각이 아니라 **자막 번호**를 받습니다. 지어낸 시각은 확인할 길이 없지만
# 지어낸 번호는 pipeline.highlights가 그 자리에서 걸러냅니다.
HIGHLIGHT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "first": {"type": "integer", "description": "시작 자막 번호"},
                        "last": {"type": "integer", "description": "끝 자막 번호(포함)"},
                        "title": {"type": "string", "description": "숏폼 제목 후보"},
                        "reason": {"type": "string", "description": "이 구간을 고른 이유"},
                    },
                    "required": ["first", "last", "title", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["picks"],
        "additionalProperties": False,
    },
}

HIGHLIGHT_SYSTEM = """당신은 긴 영상에서 숏폼으로 만들 구간을 고릅니다.

대본은 `번호<탭>시작초<탭>끝초<탭>내용` 한 줄에 하나씩 들어옵니다.

지켜야 할 것:
- **시각이 아니라 번호로 답합니다.** 시각은 우리가 대본에서 꺼내 씁니다.
- 한 구간은 {seconds}초 안팎으로 잡습니다. 5초보다 짧거나 180초보다 길면 버려집니다.
- 구간끼리 겹치지 않게 합니다.
- 말이 중간에 끊기지 않게 문장이 끝나는 자막에서 끝냅니다.
- 좋은 후보가 {limit}개보다 적으면 **적게 답합니다.** 숫자를 채우지 마세요.
- 이유는 대본에 실제로 있는 내용으로 씁니다. 없는 말을 지어내지 마세요."""


class ClaudeHighlights:
    """대본을 읽고 숏폼 후보 구간을 **제안**합니다. 적용은 사람이 합니다.

    돌려주는 것은 `pipeline.highlights.Pick` 목록입니다. 시각으로 바꾸고
    걸러내는 일은 `pipeline.highlights.accept`가 합니다. 여기서는 묻고 받아
    적기만 합니다.

    시험은 `client`에 대역을 넣습니다. `allow_paid`가 꺼져 있으면 호출 전에
    막힙니다.
    """

    def __init__(self, *, client=None, allow_paid: bool = False, model: str = HIGHLIGHT_MODEL):
        self.client, self.allow_paid, self.model = client, allow_paid, model

    def pick(self, transcript: str, *, limit: int = 5, seconds: int = 45) -> list:
        from pipeline.highlights import MAX_CHARS, Pick

        require_paid(self.allow_paid)
        if not transcript.strip():
            raise ValueError("대본이 비어 있습니다.")
        if len(transcript) > MAX_CHARS:
            raise ValueError(f"대본이 {len(transcript)}자입니다. {MAX_CHARS}자까지만 물어봅니다.")
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        # 흐름 처리를 쓰지 않습니다. 대본 크기를 위에서 막아 두었고 답이
        # 후보 몇 개뿐이라 한 번에 받습니다.
        response = self.client.messages.create(
            model=self.model,
            max_tokens=HIGHLIGHT_MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=HIGHLIGHT_SYSTEM.format(seconds=seconds, limit=limit),
            output_config={"format": HIGHLIGHT_SCHEMA},
            messages=[{"role": "user", "content": transcript}],
        )
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise ProviderError("모델이 답을 거절했습니다. 추천 없이 진행하세요.")
        if stop == "max_tokens":
            raise ProviderError("답이 잘렸습니다. 대본을 나눠서 물어보세요.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            rows = data["picks"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"추천 응답을 읽지 못했습니다: {exc}") from exc
        if not isinstance(rows, list):
            raise ProviderError("추천 응답의 picks가 목록이 아닙니다.")
        picks = []
        for row in rows:
            try:
                picks.append(
                    Pick(
                        first=int(row["first"]),
                        last=int(row["last"]),
                        title=str(row.get("title", "")),
                        reason=str(row.get("reason", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError(f"추천 항목을 읽지 못했습니다: {row!r} ({exc})") from exc
        return picks
