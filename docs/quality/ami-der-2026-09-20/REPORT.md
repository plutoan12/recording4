# 실제 영어 회의: 저장 예측과 고정 구간 DER 확인

**정확도 개선 없음.** 기존 AMI 120초 표본에 새 채점 함수를 적용한 DER은 **34.4878%**로 과거 기록과 같았습니다. 사람이 주석한 화자는 4명인데 모델은 2명만 예측했습니다.

| 항목 | 측정 |
|---|---:|
| 평가 구간 | 0–120초 |
| 정답 발화 합(겹말은 화자별 계산) | 38.92초 |
| 발화 누락 | 7.4365초 |
| 화자 혼동 | 4.8671초 |
| 무음 오검출 | 1.1190초 |
| 정답 / 예측 구간 | 20 / 24 |
| 정답 / 예측 화자 | 4 / 2 |
| DER | 0.3448781154 |

## 자료·범위

자료는 기존에 확보한 [diarizers-community/ami](https://huggingface.co/datasets/diarizers-community/ami) `ihm/test` 첫 행의 앞 120초입니다. 데이터 카드에는 영어 회의와 CC-BY-4.0이 명시되어 있습니다. 원래 출처는 [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/)이며 재배포/전처리된 주석을 사용합니다. 이번에 새 원본을 다운로드하거나 데이터 분할을 바꾸지 않았습니다. 모델 학습에 없는 화자라는 보장은 없습니다.

이것은 **영어 한 표본의 별도 진단**입니다. 실제 한·일·중 대화가 준비된 것도, 네 언어 코호트의 준비/개선 검사를 통과한 것도 아닙니다. 이 자료의 기존 reference에는 화자/시각만 있고 대사가 없어 다국어 manifest의 대사 조건을 채울 수 없습니다. 가짜 대사나 언어를 넣지 않고 `score_segments()`로 별도 채점했습니다. 완전 코호트를 요구하는 `score()` 및 준비/비교 기준은 그대로입니다.

## 실행과 검증

- 기존 기록은 집계 수치만 저장했으므로 원본을 보존한 사본에서 로컬 모델을 한 번 실행해 예측 구간도 저장했습니다. HF 오프라인 설정·캐시 모델·CPU로 132.04초 소요. 모델 구간을 다시 얻기 위한 1회 실행이며 문턱/화자 수 힌트 조정은 하지 않았습니다.
- 원본 앞 120초를 mono/16kHz WAV 사본으로 만들었습니다. 전체 주석은 기존 평가와 같은 고정 0–120초 교집합으로 준비했고 원본 주석은 바꾸지 않았습니다.
- 새 함수는 collar 0·겹말 포함·명시적 UEM 0–120초로 계산했습니다. 같은 저장 예측을 과거 암묵적 UEM 방식으로도 계산한 결과, 이 표본에서는 모든 구성값이 같았습니다. 모든 표본에서 두 방식이 같다는 뜻은 아닙니다.
- 원본/사본/정답/예측/채점 소스 SHA, 실행 버전, 소요 시간은 [result.json](result.json)에 기록했습니다. 원본 SHA 보존과 모델 입력 사본 SHA 일치를 확인했습니다.
- 원시 음원·정답 구간·예측·실행 코드는 `/Users/an-youwon/Projects/recording4-evaluation-private/ami-der-20260920`에 비공개 권한으로 보관했습니다. 실제 로그와 토큰은 커밋하지 않았습니다. 실행 버전과 워커 소스 SHA는 있으나 모델 가중치의 개별 리비전을 이번 결과에서 추가 추출하지 않았습니다.
- PR #37의 `cba3a9b` CI(Python·DER·웹·워커 이미지·스택)는 모두 통과 확인했습니다. 이번에는 운영 코드 변경 없이 측정/보고서만 추가했으므로 기존 테스트를 반복하지 않았습니다.

## 모델을 다시 실행하지 않는 재채점

저장 예측이 있으므로 앞으로 채점 함수나 지표를 확인할 때 다음처럼 재사용합니다. 평가 전용 의존성은 `scripts/requirements-der-evaluation.txt`입니다.

```bash
PYTHONPATH=scripts /tmp/r4-der-env/bin/python - <<'PY'
import json
from pathlib import Path
from score_conversation_diarization import score_segments
p = Path('/Users/an-youwon/Projects/recording4-evaluation-private/ami-der-20260920')
truth = json.loads((p / 'reference120.json').read_text())
prediction = json.loads((p / 'predictions.json').read_text())['turns']
print(score_segments(truth, prediction, 0, 120))
PY
```

## 남은 일

예측 화자 수 부족의 원인을 분리해 검증해야 합니다. 이 결과만 보고 정답 화자 수 4를 모델에 힌트로 넣거나 임계값을 조정하면 같은 표본에 맞춘 결과가 되므로 운영 개선으로 채택하지 않습니다. 실제 한·일·중 대화와 새 화자, CJK 단어 경계, CER/문자 배정 독립 채점, 50% 겹말의 기준 목소리 부재와 독립 음성·시각 검증은 남습니다. 기존 11조건 문자 배정 점수를 DER로 대체하지 않습니다.
