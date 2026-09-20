# 새 다국어 대화 자료 조사

아래는 실제 평가 완료 목록이 아니다. 제공자의 공식 설명/라이선스를 확인하고 준비 경로를 정리했다. 자료를 평가한 뒤 쉬운 사례만 고르지 않는다. 출처별 공개 test 목록 순서를 우선 고정하고, 원본/정답 해시와 전체 평가 구간을 잠근 뒤 모델을 실행한다. 학습 포함 여부가 확인되지 않은 자료를 독립 holdout이라고 부르지 않는다.

| 언어 | 후보/공식 출처 | 확인한 내용 | 남은 일 |
|---|---|---|---|
| 한국어 | [ETRI KMSAV](https://github.com/etri/kmsav) | 사람 검수 전사/다화자 영상. 자료 CC BY-NC-SA 4.0, 코드 MIT. repo `8a96a7d147eccfc8236ae78f42d32f681f5a46e2` 고정 | YouTube 음원과 release ASD 주석 수집, 고정 연속 구간의 빠진 화자/겹말 주석 확인. ASR 발화만 추린 자료를 완전 diarization 정답으로 간주하지 않음 |
| 일본어 | [RIKEN J-CRe3](https://github.com/riken-grp/J-CRe3) | 두 사람이 시나리오에 따라 대화, 음원/화자/시각/전사 제공, CC BY-SA 4.0. repo `61814236abf16258c7fb9778e32e660c1602ecfa`, test 목록 9개 | Box 배포 음원 접근/다운로드, 시나리오 대화라는 별도 조건 유지. 자발 대화와 동일시하지 않음 |
| 중국어 | [AliMeeting SLR119](https://www.openslr.org/119/) | 실제 2–4인 회의, 전사/화자 과제 지원, CC BY-SA 4.0. Eval 3.42GB/Test 8.90GB 배포 | 공식 묶음 음원/주석 확보 후 채널·고정 구간·정답 매칭. 후보 모델의 학습 포함 여부 확인 |
| 영어 | [AMI](https://huggingface.co/datasets/diarizers-community/ami) | 기존 120초는 진단/회귀에만 사용 | 기존 표본과 다른 회의 선정, 대사까지 있는 공식 주석 연결, 학습 중복 확인 |

KMSAV `data/list.txt` SHA: `d0d216feb7dd2825425a6cf9aca52cc814a8879e1b52cff9254b1284e3e961bd`. J-CRe3 `id/test.id` SHA: `667e921134736d88f0b44ccaa894c6b9d04d7e7c1025bcd00c727781f593e098`. 목록은 `/Users/an-youwon/Projects/recording4-evaluation-private/conversation-sources-20260920`에 저장했다. 이 해시는 음원/정답 해시나 평가 준비 완료를 뜻하지 않는다.

운영 모델 변경은 기존 11조건과 이 별도 코호트 모두에서 정답 증가·오배정 비증가를 확인하기 전까지 보류한다. 연구용 자료/가중치의 비상업 조건을 운영 배포 허가로 해석하지 않는다.
