"""Opt-in provider adapters. Callers must reserve budget before paid calls.

No adapter is invoked automatically by the free/local media worker. Inject clients
for contract tests. Persist returned remote ids before polling or retry decisions.
"""

from __future__ import annotations

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
