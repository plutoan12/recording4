"""설정에서 자막 표시 규칙을 만듭니다. 규칙 자체는 pipeline.subtitles에 있습니다."""

from __future__ import annotations

from adminapi.config import Settings
from pipeline.subtitles import SubtitleRules, rules_for


def rules_from_settings(settings: Settings, language: str | None = None) -> SubtitleRules:
    """설정에서 규칙을 만들고, 설정을 건드리지 않았으면 언어 기본값을 씁니다.

    자막 길이·읽기 속도 지침은 언어마다 다릅니다. 목표 언어를 아는 자리에서는
    넘겨 주세요. 모르면 설정값 그대로입니다.
    """
    base = SubtitleRules(
        max_chars_per_line=settings.subtitle_max_chars_per_line,
        max_lines=settings.subtitle_max_lines,
        max_cps=settings.subtitle_max_cps,
        min_duration=settings.subtitle_min_duration,
        max_duration=settings.subtitle_max_duration,
    )
    return rules_for(language, base)
