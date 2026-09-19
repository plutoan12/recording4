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
        return output


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
