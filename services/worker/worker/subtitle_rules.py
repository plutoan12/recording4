"""설정에서 자막 표시 규칙을 만듭니다. 규칙 자체는 pipeline.subtitles에 있습니다."""

from __future__ import annotations

from adminapi.config import Settings
from pipeline.subtitles import SubtitleRules


def rules_from_settings(settings: Settings) -> SubtitleRules:
    return SubtitleRules(
        max_chars_per_line=settings.subtitle_max_chars_per_line,
        max_lines=settings.subtitle_max_lines,
        max_cps=settings.subtitle_max_cps,
        min_duration=settings.subtitle_min_duration,
        max_duration=settings.subtitle_max_duration,
    )
