"""자막 템플릿이 쓰는 글꼴 목록. 출처·커밋·체크섬·라이선스를 함께 둡니다.

글꼴 파일은 저장소에 넣지 않습니다(수십 MB). 워커 이미지를 만들 때
`scripts/fetch_fonts.py`가 이 목록대로 받아 체크섬을 확인하고 설치합니다.
출처는 커밋 해시로 고정해 같은 바이트가 다시 오도록 합니다.

모두 SIL Open Font License 1.1이라 영상에 구워 배포해도 됩니다. Noto Sans CJK KR은
워커 이미지의 fonts-noto-cjk 패키지가 이미 설치하므로 여기 없습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

GOOGLE_FONTS_COMMIT = "f2bd09badbc763d8757951d52deec29da27e85fb"
GALMURI_COMMIT = "71e1cacf1437a11220307120e63e30bc275312d4"

_GOOGLE = f"https://raw.githubusercontent.com/google/fonts/{GOOGLE_FONTS_COMMIT}/ofl"
_GALMURI = f"https://raw.githubusercontent.com/quiple/galmuri/{GALMURI_COMMIT}/dist"

SYSTEM_FONTS = ("Noto Sans CJK KR",)
"""워커 이미지에 패키지로 이미 있는 글꼴. 받지 않습니다."""


@dataclass(frozen=True, slots=True)
class FontSource:
    # ASS Fontname에 쓰는 이름. 파일 name 테이블의 family(nameID 1)와 같아야 libass가
    # 찾습니다. Google Fonts 이름과 다른 것이 있습니다(Nanum Pen Script → "Nanum Pen",
    # Galmuri11 → "Galmuri11 Regular"). scripts/fetch_fonts.py가 fc-scan으로 확인합니다.
    family: str
    filename: str
    url: str
    sha256: str
    license: str = "OFL-1.1"
    license_url: str = ""


def _google(family: str, folder: str, filename: str, sha256: str) -> FontSource:
    return FontSource(
        family=family,
        filename=filename,
        url=f"{_GOOGLE}/{folder}/{filename}",
        sha256=sha256,
        license_url=f"https://github.com/google/fonts/blob/{GOOGLE_FONTS_COMMIT}/ofl/{folder}/OFL.txt",
    )


FONT_SOURCES: tuple[FontSource, ...] = (
    _google(
        "Jua",
        "jua",
        "Jua-Regular.ttf",
        "769677aef240bfc3b9965f2b50748075bff885e6c6992fc591a3fb268279f898",
    ),
    _google(
        "Black Han Sans",
        "blackhansans",
        "BlackHanSans-Regular.ttf",
        "31960809284026681774a8e52dc19ebcad26cf69b0ad9d560f288296fbb52739",
    ),
    _google(
        "Bagel Fat One",
        "bagelfatone",
        "BagelFatOne-Regular.ttf",
        "9286944032c5a9b20ad70940105417beae14013e0b4f5fc292425afdc4330245",
    ),
    _google(
        "Gaegu",
        "gaegu",
        "Gaegu-Bold.ttf",
        "cc38a4af9506a45254d1ce07c589ec473d9e5f0be319e5a77b17c214903f8c1c",
    ),
    _google(
        "Do Hyeon",
        "dohyeon",
        "DoHyeon-Regular.ttf",
        "35644be7f28e0a68a447b1f7af351dcde5674b870f24f7b5f43e26d00b4ab653",
    ),
    _google(
        "Gowun Batang",
        "gowunbatang",
        "GowunBatang-Regular.ttf",
        "466c593e7147412e748af4856d5ad14709b5a860bdf62b9c2546f2c5874e9849",
    ),
    _google(
        "Nanum Pen",
        "nanumpenscript",
        "NanumPenScript-Regular.ttf",
        "6f0d1ab29c7894010dc88831fb7a0a51edb79136e450344183de5b1a8b52bd43",
    ),
    _google(
        "Gugi",
        "gugi",
        "Gugi-Regular.ttf",
        "c0b1f979979cfc309fb2438fa9464f96173353e0c4842cc7a5919658184ed9d3",
    ),
    _google(
        "Moirai One",
        "moiraione",
        "MoiraiOne-Regular.ttf",
        "432f48aa773510211ac50c9d8130e50fe135c4d8c05645828ccde7e652ea8106",
    ),
    _google(
        "Dongle",
        "dongle",
        "Dongle-Bold.ttf",
        "944c498c0d1a1832ab36f173b1b3aa5ae77b2a914e00c4d79e05338fae36472d",
    ),
    _google(
        "Single Day",
        "singleday",
        "SingleDay-Regular.ttf",
        "716ff67a4b0675b35c26d60a4bb83173f7d153ab754474ed36c3369593ca1ca8",
    ),
    _google(
        "Hi Melody",
        "himelody",
        "HiMelody-Regular.ttf",
        "360d2c0a880918aa48328d1d9219f5390788d09a1c9353e12b471de018673ae6",
    ),
    _google(
        "Gamja Flower",
        "gamjaflower",
        "GamjaFlower-Regular.ttf",
        "ece32819ed58536355a49a095b0cdfdd3b8ef9081c5ed9ca1cef8f5d999ae1ac",
    ),
    _google(
        "East Sea Dokdo",
        "eastseadokdo",
        "EastSeaDokdo-Regular.ttf",
        "8cebb39d375134fdbcedef9bf4ec4f6c3f02c39ed0aacd6e83f7a0f435e593b2",
    ),
    FontSource(
        family="Galmuri11 Regular",
        filename="Galmuri11.ttf",
        url=f"{_GALMURI}/Galmuri11.ttf",
        sha256="e24256f42e43713d2ea086a1e1669d78b968f5b3cc547e5c157f0606ffa5def1",
        license_url=f"https://github.com/quiple/galmuri/blob/{GALMURI_COMMIT}/OFL.md",
    ),
    FontSource(
        family="Galmuri9 Regular",
        filename="Galmuri9.ttf",
        url=f"{_GALMURI}/Galmuri9.ttf",
        sha256="e84e821b18be15b9e3a907ceb83cfba25fabf51c80b7edf0d2921cf8f8e1a11d",
        license_url=f"https://github.com/quiple/galmuri/blob/{GALMURI_COMMIT}/OFL.md",
    ),
)

FONT_FAMILIES: frozenset[str] = frozenset(SYSTEM_FONTS) | frozenset(
    source.family for source in FONT_SOURCES
)
"""템플릿이 써도 되는 글꼴 이름. 없는 이름은 libass가 기본 글꼴로 대체해 모양이 달라집니다."""

# 관리화면 미리보기용. 같은 글꼴을 Google Fonts CSS로 불러 CSS로 흉내 냅니다.
# 실제 렌더는 libass이므로 화면 미리보기와 완전히 같지는 않습니다.
GOOGLE_FONTS_CSS_FAMILIES: tuple[str, ...] = tuple(
    {"Nanum Pen": "Nanum Pen Script"}.get(source.family, source.family)
    for source in FONT_SOURCES
    if not source.family.startswith("Galmuri")
)
