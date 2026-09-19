"""설정에서 자막 표시 규칙을 만듭니다. 규칙 자체는 pipeline.subtitles에 있습니다.

워커에도 같은 일을 하는 `worker/subtitle_rules.py`가 있습니다. API는 워커
패키지를 불러오지 않으므로 각자 둡니다.
"""

from __future__ import annotations

from adminapi.config import get_settings
from pipeline.subtitles import SubtitleRules


def subtitle_rules() -> SubtitleRules:
    s = get_settings()
    return SubtitleRules(
        max_chars_per_line=s.subtitle_max_chars_per_line,
        max_lines=s.subtitle_max_lines,
        max_cps=s.subtitle_max_cps,
        min_duration=s.subtitle_min_duration,
        max_duration=s.subtitle_max_duration,
    )
