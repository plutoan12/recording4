"""Opt-in provider adapters. Callers must reserve budget before paid calls.

No adapter is invoked automatically by the free/local media worker. Inject clients
for contract tests. Persist returned remote ids before polling or retry decisions.
"""

from __future__ import annotations

import json
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

    호출마다 `missing_terms`에 **번역문에서 사라진 용어**가 자리 번호별로
    남습니다. 용어가 빠졌다고 번역을 버리지는 않습니다. 세어서 보여 주는
    것까지가 몫입니다.
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
        self.missing_terms: dict[int, list[str]] = {}

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
        self.missing_terms = {}
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
                gone = missing(output[index], marked[index][1])
                if gone:
                    self.missing_terms[index] = gone
        if self.missing_terms:
            logger.warning("번역문에서 빠진 용어: %s", self.missing_terms)

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


class ClaudeTranslator:
    """어색한 자막만 다시 번역합니다. 앞뒤 자막을 문맥으로 같이 넘깁니다.

    전체를 LLM에 맡기지 않습니다. 기계 번역이 대부분을 처리하고, 여기서는
    `pipeline.translation_review`가 고른 몇 개만 다시 씁니다. 고르는 수에
    상한이 있어(기본 30%) 비용이 번역량에 비례해 뛰지 않습니다.

    응답은 **입력과 같은 개수의 JSON 배열**이어야 합니다. 개수가 다르거나
    JSON이 아니면 `ProviderError`를 냅니다. 부르는 쪽은 그때 기계 번역
    결과를 그대로 씁니다. **다시 쓰기에 실패해도 자막은 남습니다.**
    """

    URL = "https://api.anthropic.com/v1/messages"
    VERSION = "2023-06-01"
    # 자막 한 줄이 길어야 수백 자입니다. 넉넉히 잡되 폭주를 막습니다.
    MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client,
        model: str,
        allow_paid: bool = False,
    ):
        self.api_key, self.client, self.model = api_key, client, model
        self.allow_paid = allow_paid
        self.usage: dict[str, int] = {}

    def prompt(
        self,
        items: list[dict],
        target: str,
        source: str | None,
        glossary: Glossary | None,
    ) -> str:
        lines = [
            "아래는 영상 자막입니다. 기계 번역이 어색하게 옮긴 자막을 다시 번역합니다.",
            f"원문 언어: {source or '자동 감지'} / 목표 언어: {target}",
            "",
            "규칙:",
            "- `다시 번역할 자막`의 각 항목을 목표 언어로 옮깁니다.",
            "- 자막이므로 **짧고 말하듯이** 씁니다. 설명을 덧붙이지 않습니다.",
            "- 앞뒤 자막은 문맥으로만 쓰고 번역하지 않습니다.",
            "- 줄바꿈을 넣지 않습니다. 한 항목은 한 줄입니다.",
        ]
        if glossary and glossary.entries:
            pairs = ", ".join(f"{key} → {value}" for key, value in glossary.entries.items())
            lines.append(f"- 다음 표기를 **그대로** 씁니다: {pairs}")
        lines += [
            "",
            "출력: 설명 없이 JSON 배열 하나만. 항목 수는 입력과 같아야 합니다.",
            "",
            "앞뒤 문맥:",
            json.dumps(
                [{"원문": item["context"]} for item in items], ensure_ascii=False, indent=None
            ),
            "",
            "다시 번역할 자막:",
            json.dumps(
                [{"원문": item["source"], "기계 번역": item["draft"]} for item in items],
                ensure_ascii=False,
            ),
        ]
        return "\n".join(lines)

    def retranslate(
        self,
        items: list[dict],
        target: str,
        source: str | None = None,
        *,
        glossary: Glossary | None = None,
    ) -> list[str]:
        """`items`는 `{"source", "draft", "context"}` 목록입니다."""
        require_paid(self.allow_paid)
        if not items:
            raise ValueError("다시 번역할 자막이 없습니다.")
        response = self.client.post(
            self.URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": self.VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.MAX_TOKENS,
                "messages": [
                    {"role": "user", "content": self.prompt(items, target, source, glossary)}
                ],
            },
            timeout=120,
        )
        if response.status_code != 200:
            raise ProviderError(f"LLM 재번역 실패: HTTP {response.status_code}")
        body = response.json()
        self.usage = body.get("usage") or {}
        if body.get("stop_reason") == "max_tokens":
            raise ProviderError("LLM 재번역이 길이 제한에서 잘렸습니다.")
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        )
        return self._parse(text, len(items))

    @staticmethod
    def _parse(text: str, count: int) -> list[str]:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise ProviderError("LLM 재번역 응답에서 JSON 배열을 찾지 못했습니다.")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            raise ProviderError("LLM 재번역 응답이 JSON이 아닙니다.") from None
        if not isinstance(parsed, list) or len(parsed) != count:
            raise ProviderError("LLM 재번역 응답 수가 입력과 다릅니다.")
        output = []
        for item in parsed:
            value = item.get("번역") if isinstance(item, dict) else item
            if not isinstance(value, str) or not value.strip():
                raise ProviderError("LLM 재번역 응답에 빈 항목이 있습니다.")
            output.append(" ".join(value.split()))
        return output
