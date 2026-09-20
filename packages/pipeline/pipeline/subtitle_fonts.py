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
    _google(
        "Gasoek One",
        "gasoekone",
        "GasoekOne-Regular.ttf",
        "73a6b8e0d12a56f0a070f19b44a93ae050f98eb926da5d2a7c8d6db92bd8d9c3",
    ),
    _google(
        "Kirang Haerang",
        "kiranghaerang",
        "KirangHaerang-Regular.ttf",
        "d677d28d466989017c520f00a2a7794ea581ea3d9fa9a830fbb44f1015eac72d",
    ),
    _google(
        "Yeon Sung",
        "yeonsung",
        "YeonSung-Regular.ttf",
        "49ac2a11009f5f58307d377911eb45d210cf4c1d379d9eca38fb4cdad5491ef6",
    ),
    _google(
        "Sunflower",
        "sunflower",
        "Sunflower-Bold.ttf",
        "6b033627817f6619433afe82028013dc45a78ff82406b1dbe5b16e1bbc370e0a",
    ),
    _google(
        "Cute Font",
        "cutefont",
        "CuteFont-Regular.ttf",
        "c403227fe6288a8c1423ca48e93fd7efc81e3b81053f7d17adcf659bd95fa4c3",
    ),
    _google(
        "Nanum Brush Script",
        "nanumbrushscript",
        "NanumBrushScript-Regular.ttf",
        "27ceaf578c96f594cdf07fe0181b251790acbb746a164e45c1f6473f89911a31",
    ),
    _google(
        "Song Myung",
        "songmyung",
        "SongMyung-Regular.ttf",
        "7f90ab20250911560212cc5819c7b205f9c6644bb96b65095d89fcae096bbf58",
    ),
    _google(
        "Orbit",
        "orbit",
        "Orbit-Regular.ttf",
        "5d0206fb0a9e3eeac51aff8d4a6dbb7613d63fc435f1a51f96dc35cefb5f9f87",
    ),
    _google(
        "Diphylleia",
        "diphylleia",
        "Diphylleia-Regular.ttf",
        "a0f505e19758bbe69da3e1cdd89fac74e69e851aa82195a61c861bcee7a53293",
    ),
    _google(
        "Dokdo",
        "dokdo",
        "Dokdo-Regular.ttf",
        "5b3a3d8d28af31fa9adec3fc5da81a88b52e1ff39ed3930c1db787aa4e79c36d",
    ),
    _google(
        "Gothic A1",
        "gothica1",
        "GothicA1-Black.ttf",
        "6398ff5c6923c74cb453390892dcb982ec0a6c43b35da8590a8f32702d8c079d",
    ),
    _google(
        "Poor Story",
        "poorstory",
        "PoorStory-Regular.ttf",
        "831ab87f7b5463f9cd83ac249bf386816f3a478f1d226427c88cac907adb7ee2",
    ),
    _google(
        "Grandiflora One",
        "grandifloraone",
        "GrandifloraOne-Regular.ttf",
        "592da2454a6626ee68558e220df28808b95f7dd140cd1ceb8a0d72b777f157ad",
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

# 굵기 하나만 받는 글꼴. Google Fonts CSS에서 같은 굵기를 요청해야 화면 미리보기가 같습니다.
GOOGLE_FONTS_CSS_WEIGHTS: dict[str, int] = {
    "Gaegu": 700,
    "Dongle": 700,
    "Sunflower": 700,
    "Gothic A1": 900,
}
