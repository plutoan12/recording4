"""설정에서 자막 표시 규칙을 만듭니다. 규칙 자체는 pipeline.subtitles에 있습니다.

워커에도 같은 일을 하는 `worker/subtitle_rules.py`가 있습니다. API는 워커
패키지를 불러오지 않으므로 각자 둡니다. 두 쪽이 같은 규칙을 내야 하므로 언어
처리도 같게 유지합니다.
"""

from __future__ import annotations

from dataclasses import fields

from adminapi.config import get_settings
from pipeline.subtitles import SubtitleRules, rules_for


def subtitle_rules(language: str | None = None) -> SubtitleRules:
    """설정에서 규칙을 만들고, 설정을 건드리지 않았으면 언어 기본값을 씁니다.

    자막 길이·읽기 속도 지침은 언어마다 다릅니다. 렌더가 언어를 넘겨 만든 자막을
    파일로 내보낼 때는 같은 언어를 넘겨야 화면 자막과 줄이 같습니다.
    """
    s = get_settings()
    base = SubtitleRules(
        max_chars_per_line=s.subtitle_max_chars_per_line,
        max_lines=s.subtitle_max_lines,
        max_cps=s.subtitle_max_cps,
        min_duration=s.subtitle_min_duration,
        max_duration=s.subtitle_max_duration,
    )
    return rules_for(language, base)


def rules_from_record(saved: object, language: str | None = None) -> tuple[SubtitleRules, str]:
    """렌더가 남긴 규칙 기록을 되살립니다. 규칙과, 그것을 어디서 얻었는지 함께 돌려줍니다.

    설정(`R4_SUBTITLE_*`)을 렌더 뒤에 바꾸면 지금 설정으로 다시 계산한 자막은
    영상에 구워진 자막과 줄바꿈·분할이 달라집니다. 사람은 같은 자막이라고 믿고
    올립니다. 그래서 렌더가 남긴 규칙이 있으면 그것을 씁니다.

    남은 것이 없거나(기록 전에 렌더한 결과물, 아직 렌더하지 않은 작업) 기록이
    깨졌으면 지금 설정을 쓰되, `settings`로 그 사실을 함께 돌려줍니다. 모르는
    것을 아는 척하지 않습니다.
    """
    if isinstance(saved, dict):
        names = {f.name for f in fields(SubtitleRules)}
        try:
            return SubtitleRules(**{k: v for k, v in saved.items() if k in names}), "rendered"
        except (TypeError, ValueError):
            # 기록이 깨졌습니다. 지금 설정으로 만들되 그렇다고 알립니다.
            pass
    return subtitle_rules(language), "settings"
