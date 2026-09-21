"""Opt-in provider adapters. Callers must reserve budget before paid calls.

No adapter is invoked automatically by the free/local media worker. Inject clients
for contract tests. Persist returned remote ids before polling or retry decisions.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from pipeline.glossary import Glossary, missing, protect, restore

logger = logging.getLogger(__name__)

# Google 자체 용어집 리소스 이름. 용어집은 `global` 위치를 지원하지 않습니다.
GLOSSARY_RESOURCE = re.compile(r"^projects/[^/]+/locations/[^/]+/glossaries/[^/]+$")


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
    """Google 번역. 용어집은 두 갈래 중 하나로 적용됩니다.

    `glossary_resource`가 설정되어 있으면 **Google 자체 용어집**을 씁니다.
    어미 변화까지 Google이 처리하지만, 용어 파일을 Cloud Storage에 두고
    `global`이 아닌 지역에 리소스를 만들어 두어야 합니다.

    없으면 `translate()`에 넘긴 **우리 용어집**을 씁니다. 용어가 걸린 문장만
    `text/html`로 바꿔 그 자리를 `translate="no"`로 감싸 보냅니다. 걸리지
    않은 문장은 지금까지와 똑같이 `text/plain`으로 갑니다. 방식과 한계는
    `pipeline.glossary`에 적어 두었습니다.

    호출마다 `missing_terms`에 **번역문에서 사라진 용어**가 남습니다. 용어가
    빠졌다고 번역을 버리지는 않습니다. 세어서 보여 주는 것까지가 몫입니다.
    """

    def __init__(
        self,
        project: str,
        *,
        client=None,
        allow_paid: bool = False,
        glossary_resource: str | None = None,
    ):
        if glossary_resource and not GLOSSARY_RESOURCE.match(glossary_resource):
            raise ValueError(
                "용어집 리소스 이름은 projects/…/locations/…/glossaries/… 형식이어야 합니다."
            )
        if glossary_resource and glossary_resource.split("/")[3] == "global":
            raise ValueError("Google 용어집은 global 위치를 지원하지 않습니다. 지역을 고르세요.")
        self.project, self.client, self.allow_paid = project, client, allow_paid
        self.glossary_resource = glossary_resource
        self.missing_terms: list[str] = []

    @property
    def parent(self) -> str:
        if self.glossary_resource:
            return "/".join(self.glossary_resource.split("/")[:4])
        return f"projects/{self.project}/locations/global"

    def _call(self, texts: list[str], target: str, source: str | None, *, html: bool) -> list[str]:
        request = {
            "parent": self.parent,
            "contents": texts,
            "target_language_code": target,
            "mime_type": "text/html" if html else "text/plain",
        }
        if source:
            request["source_language_code"] = source
        if self.glossary_resource:
            request["glossary_config"] = {"glossary": self.glossary_resource}
        # Disable SDK automatic retries: the caller owns budget and retry policy.
        response = self.client.translate_text(request=request, retry=None, timeout=60)
        items = list(response.translations)
        if self.glossary_resource:
            # 용어집을 거친 결과는 별도 자리에 옵니다. 비어 있으면 원래 자리를 씁니다.
            items = list(getattr(response, "glossary_translations", None) or items)
        output = [item.translated_text for item in items]
        if len(output) != len(texts):
            raise ProviderError("번역 응답 수가 입력과 다릅니다.")
        return output

    def translate(
        self,
        texts: list[str],
        target: str,
        source: str | None = None,
        *,
        glossary: Glossary | None = None,
    ) -> list[str]:
        require_paid(self.allow_paid)
        if not texts or sum(map(len, texts)) > 25000:
            raise ValueError("번역 배치는 비어 있지 않고 25,000자 이하여야 합니다.")
        if self.client is None:
            from google.cloud import translate_v3

            self.client = translate_v3.TranslationServiceClient()
        self.missing_terms = []
        if self.glossary_resource:
            glossary = None  # Google이 처리하므로 우리 표시는 넣지 않습니다.
        marked = [protect(text, glossary) for text in texts]
        output: list[str] = [""] * len(texts)

        plain = [index for index, (_, terms) in enumerate(marked) if not terms]
        if plain:
            for index, translated in zip(
                plain,
                self._call([texts[i] for i in plain], target, source, html=False),
                strict=True,
            ):
                output[index] = translated

        # 용어가 걸린 문장만 HTML로 보냅니다. Google은 표시 글자도 세어 청구하므로
        # 걸린 자리마다 28자(`<span translate="no">`+`</span>`)와 원문·번역 표기의
        # 길이 차만큼 더 나옵니다. 예산 계산도 같은 글자를 셉니다(`paid_estimate`).
        tagged = [index for index, (_, terms) in enumerate(marked) if terms]
        if tagged:
            for index, translated in zip(
                tagged,
                self._call([marked[i][0] for i in tagged], target, source, html=True),
                strict=True,
            ):
                output[index] = restore(translated)
                self.missing_terms += missing(output[index], marked[index][1])
        if self.missing_terms:
            logger.warning(
                "번역문에서 빠진 용어 %d개: %s", len(self.missing_terms), self.missing_terms
            )

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
