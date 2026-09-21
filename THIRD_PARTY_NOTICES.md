# 제3자 코드 고지

이 저장소에 옮겨 온 코드와 원 저작권·라이선스입니다. 구조만 참고한 것도 함께 적습니다.

## machinewrapped/llm-subtrans (MIT)

`packages/pipeline/pipeline/batching.py`는 `PySubtrans/SubtitleBatcher.py`를 옮긴 것입니다.
번역 프롬프트 규칙 문구(`services/worker/worker/providers.py`의 `TRANSLATE_SYSTEM`,
`RETRY_INSTRUCTIONS`)는 `instructions/instructions.txt`와 재시도 지시를 참고했습니다.

    MIT License
    Copyright (c) 2023 machinewrapped

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## rockbenben/subtitle-translator (MIT)

`packages/pipeline/pipeline/glossary.py`의 `terms_in_text`·`violations`·`apply_terms`·
`prompt_block`은 `src/app/lib/translation/glossary.ts`를 옮긴 것이고, 번역 기억 키
(`services/worker/worker/workflow_tasks.py`의 `draft_suffix`/`final_suffix`)는
`src/app/lib/translation/cache.ts`의 `generateCacheSuffix` 방식입니다. 라이선스 본문은
위 MIT와 같으며 저작권자는 rockbenben입니다.

## azratul/llm-subs (GPL-3.0) — 구조만 참고

GPL이라 코드는 옮기지 않았습니다. `packages/pipeline/pipeline/translation_jobs.py`는
그 프로젝트의 job protocol(번호 줄 + 앞뒤 문맥 + 묶음별 규칙, 답은 번호→번역문)과
style guide(honorifics keep, names keep_original) 구조를 따로 구현한 것입니다.

## yazinsai/srt-ai (라이선스 파일 없음) — 방식만 참고

토큰 상한으로 묶음을 자르고 "입력과 정확히 같은 수의 구간을 내라"는 규칙을 프롬프트에
두는 방식만 참고했습니다. 코드는 옮기지 않았습니다.

## WyattBlue/auto-editor (Unlicense, 퍼블릭 도메인)

`packages/pipeline/pipeline/cuts.py`의 `apply_margin`·`smooth`는 `src/lib/editutil.nim`의
`mutMargin`·`smoothing`을 파이썬으로 옮긴 것입니다. 둘 다보다 짧은 구간 하나가 참↔거짓을
영원히 오가는 것을 두 번 전 상태까지 견주어 막는 부분도 그 주석에서 왔습니다.

    This is free and unencumbered software released into the public domain.

    Anyone is free to copy, modify, publish, use, compile, sell, or distribute this
    software, either in source code form or as a compiled binary, for any purpose,
    commercial or non-commercial, and by any means.

## carykh/jumpcutter (MIT) — 읽었으나 쓰지 않음

프레임별 소리 크기를 파일에서 가장 큰 소리와 견주어 무음을 판정하는 방식을 봤지만
**넣지 않았습니다.** 이 저장소는 실제 녹음에서 그 방식이 발화를 못 찾는 것을 이미
쟀습니다(`worker.analysis.vad_spans` 주석). 발화 구간은 VAD가 찾고, auto-editor에서
가져온 다듬기만 그 위에 겁니다.

