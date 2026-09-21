"""지원 언어와 번역 방향. 언어 목록은 **여기 한 곳**에서만 바꿉니다.

핵심 네 언어(ko·en·ja·zh)는 서로 모든 방향을 지원합니다. 추가 언어는 우선
한국어에서만 나가지만, 판정은 전부 (source, target) 쌍으로 하므로 `EXTRA_SOURCES`에
언어를 더하면 그 언어에서 나가는 방향이 열립니다. 코드 곳곳에 언어를 적지 말고
이 모듈을 부릅니다. 관리화면도 API(`/workflow/configuration`)로 이 목록을 받습니다.
"""

from __future__ import annotations

LANGUAGES: dict[str, str] = {
    "ko": "한국어",
    "en": "영어",
    "ja": "일본어",
    "zh": "중국어",
    "es": "스페인어",
    "id": "인도네시아어",
    "th": "태국어",
    "pt": "포르투갈어",
    "vi": "베트남어",
    "hi": "힌디어",
}

CORE: tuple[str, ...] = ("ko", "en", "ja", "zh")
TIER2: tuple[str, ...] = ("es", "id", "th", "pt")
TIER3: tuple[str, ...] = ("vi", "hi")
# 추가 언어(TIER2·TIER3)로 나가는 출발 언어. 상호 번역으로 넓히려면 여기에 더합니다.
EXTRA_SOURCES: tuple[str, ...] = ("ko",)

TIERS: dict[str, int] = {
    **dict.fromkeys(CORE, 1),
    **dict.fromkeys(TIER2, 2),
    **dict.fromkeys(TIER3, 3),
}


def normalize(code: str) -> str:
    """`zh-CN` → `zh`. 지역 표기는 방향 판정에 쓰지 않습니다."""
    return code.split("-")[0].lower()


def _directions() -> frozenset[tuple[str, str]]:
    pairs = {(s, t) for s in CORE for t in CORE if s != t}
    pairs |= {(s, t) for s in EXTRA_SOURCES for t in TIER2 + TIER3}
    return frozenset(pairs)


DIRECTIONS: frozenset[tuple[str, str]] = _directions()


def is_supported(source: str | None, target: str) -> bool:
    """이 방향을 번역할 수 있는지.

    같은 언어는 번역 없이 지나가므로 허용합니다. 출발 언어를 모르면(자동 감지)
    목표 언어가 어느 방향에든 목표로 있으면 허용합니다.
    """
    t = normalize(target)
    if source is None:
        return any(x == t for _, x in DIRECTIONS)
    s = normalize(source)
    return s == t or (s, t) in DIRECTIONS


def sources() -> list[str]:
    return [code for code in LANGUAGES if any(s == code for s, _ in DIRECTIONS)]


def targets_for(source: str | None) -> list[str]:
    """이 출발 언어에서 갈 수 있는 목표 언어. 같은 언어는 번역이 아니므로 뺍니다."""
    return [
        code
        for code in LANGUAGES
        if is_supported(source, code) and (source is None or normalize(source) != code)
    ]


def catalogue() -> dict:
    """관리화면에 주는 목록. 화면은 이것만 보고 선택지를 그립니다."""
    return {
        "languages": [
            {"code": code, "label": label, "tier": TIERS[code]} for code, label in LANGUAGES.items()
        ],
        "sources": sources(),
        "directions": sorted(DIRECTIONS),
    }


# 공급자별 언어 코드. 여기 없는 언어는 그 공급자로 보내기 전에 막힙니다.
# DeepL: https://developers.deepl.com/docs/resources/supported-languages (확인일 2026-09-21,
# 힌디어·태국어·베트남어 지원 여부는 실제 호출로 확인하지 않았습니다).
DEEPL_TARGETS: dict[str, str] = {
    "ko": "KO",
    "en": "EN-US",
    "ja": "JA",
    "zh": "ZH-HANS",
    "es": "ES",
    "id": "ID",
    "th": "TH",
    "pt": "PT-BR",
    "vi": "VI",
    "hi": "HI",
}
DEEPL_SOURCES: dict[str, str] = {code: value.split("-")[0] for code, value in DEEPL_TARGETS.items()}

# Hugging Face NLLB-200(facebook/nllb-200-distilled-600M 등)의 FLORES-200 코드.
NLLB_CODES: dict[str, str] = {
    "ko": "kor_Hang",
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "zh": "zho_Hans",
    "es": "spa_Latn",
    "id": "ind_Latn",
    "th": "tha_Thai",
    "pt": "por_Latn",
    "vi": "vie_Latn",
    "hi": "hin_Deva",
}


def provider_code(table: dict[str, str], code: str | None, provider: str) -> str | None:
    """공급자 코드로 바꿉니다. 모르는 언어는 조용히 넘기지 않고 막습니다."""
    if code is None:
        return None
    try:
        return table[normalize(code)]
    except KeyError:
        raise ValueError(f"{provider}가 지원하지 않는 언어입니다: {code}") from None
