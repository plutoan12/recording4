# 기술 선택과 결정 기록

상태: 아래 선택은 설계 추천안입니다. 사용자 확정이나 실제 성능 검증을 의미하지 않습니다. 공식 문서 확인일: 2026-09-18. 구현 시 모델·지원 언어·요금·제한을 다시 확인합니다.

## 추천 구성

| 영역 | 추천 | 이유 / 검증할 사항 |
|---|---|---|
| 관리화면 | React + TypeScript + Vite | 대본 편집·미리보기 중심의 관리자 앱. 공개 검색 최적화는 초기 요구사항이 아님 |
| 관리 API | Python FastAPI | AI 호출과 영상 처리에 같은 언어 사용 |
| DB | PostgreSQL | 버전·승인·게시 이력의 관계 및 트랜잭션 관리 |
| 큐 | Celery + Redis | 워커 분리와 재시도. 장시간 실행·재전달·재시작 검증 필요 |
| 저장소 | Amazon S3 | 서명 URL과 분할 업로드. 보관·전송 비용 측정 필요 |
| 영상 처리 | FFmpeg + ffprobe | 음성 추출, 길이 검사, 자막·음성 합성 |
| STT | Google Cloud Speech-to-Text | 시간 정보 및 화자 정보 활용. 언어·모델별 지원 확인 |
| 번역 | Google Cloud Translation Advanced | 용어집 활용. 더빙에 맞는 표현·길이는 검수 및 편집 필요 |
| 더빙 | ElevenLabs API | 음성 및 타이밍 정보. 대상 언어와 음성 품질 샘플 평가 |
| 립싱크 | Sync API 후보 | 초기 자체 GPU 운영 부담 감소. 실제 장면과 화자 수로 평가 후 확정 |
| 배포 | Docker Compose + Linux | 초기 단일 서버 구성. 부하 증가 시 워커 분리 |
| 게시 | YouTube Data API + OAuth | 채널 인증, 이어 올리기, 공개 예약 |

## 공식 근거와 제약

- [GitHub Actions 실행 제한](https://docs.github.com/en/enterprise-cloud%40latest/actions/reference/limits): GitHub 호스팅 러너는 작업당 6시간 제한이 있습니다. 영상 작업 상태를 Actions 실행에 종속시키지 않습니다.
- [S3 서명 URL](https://docs.aws.amazon.com/AmazonS3/latest/userguide/PresignedUrlUploadObject.html): 브라우저가 AWS 자격증명을 보유하지 않고 직접 업로드할 수 있습니다. 같은 키를 덮어쓸 수 있으므로 고유한 파일 키와 업로드 완료 검증을 사용합니다.
- [S3 분할 업로드](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html): 큰 원본을 부분 단위로 전송합니다. 미완료 업로드 정리 정책도 설정합니다.
- [Celery 설정](https://docs.celeryq.dev/en/main/userguide/configuration.html): 재전달 가능성을 고려해 같은 작업을 여러 번 실행해도 문제가 없도록 구현합니다. Redis의 visibility timeout은 작업 길이에 맞춰 검토합니다.
- [Google STT V2](https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v2/projects.locations.recognizers): 단어별 시간·화자 설정이 있습니다. 모든 모델·언어가 같은 옵션을 지원한다고 가정하지 않습니다.
- [Cloud Translation](https://docs.cloud.google.com/translate/docs/api-overview): Advanced의 용어집을 활용합니다. 번역 품질과 더빙 길이 적합성은 별도 평가 대상입니다.
- [ElevenLabs 타이밍 응답](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps): 음성과 문자 타이밍을 받아 문장 타이밍·자막으로 변환합니다. 원본 구간 길이에 자동으로 맞춰진다는 의미는 아닙니다.
- [Sync 문서](https://sync.so/docs/introduction): 립싱크 후보입니다. 다중 화자, 얼굴 가림, 빠른 장면 전환 등 대표 입력으로 적용 가능성을 확인합니다.
- [YouTube 영상 리소스](https://developers.google.com/youtube/v3/docs/videos): 예약 공개는 비공개이고 아직 공개된 적 없는 영상에 설정합니다. 2020-07-28 이후 생성된 미검증 API 프로젝트의 업로드는 비공개로 제한되며 제한 해제에 감사가 필요할 수 있습니다. 계정 준비 단계에서 확인합니다.
- [YouTube 이어 올리기](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol): 세션 URL과 전송 상태를 보존해 중단 후 재개합니다. 성공 응답을 잃었을 때도 기존 세션부터 확인합니다.
- [YouTube 쿼터 계산기](https://developers.google.com/youtube/v3/determine_quota_cost), [쿼터와 감사](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits): 업로드는 비용이 큰 호출이며 업로드·검색을 별도 쿼터로 분리하는 변경이 안내되어 있습니다. 하루 업로드 가능 편수가 처리량 상한이 될 수 있습니다. **2026-09-18 검토 시점에 이 두 페이지는 작업 환경의 네트워크 정책으로 직접 열지 못했습니다. 수치를 이 문서에 옮기지 않았으므로 계정 준비 단계에서 현재 쿼터와 상향 신청 절차를 직접 확인합니다.**
- [YouTube 영상 수정](https://developers.google.com/youtube/v3/docs/videos/update): 제목·설명·공개 상태는 수정할 수 있습니다. 업로드된 영상의 파일 교체는 지원되지 않는 것으로 보고 설계했습니다. 계정 준비 단계에서 수정 가능한 범위를 확인합니다.

## 변경 기록

| 날짜 | 상태 | 내용 | 이유 |
|---|---|---|---|
| 2026-09-18 | 제안 | Python API·워커 + 객체 저장소 + PostgreSQL | 영상 처리와 상태 관리를 분리 |
| 2026-09-18 | 제안 | 외부 AI API 우선, 립싱크는 확장 단계 | 먼저 기본 파이프라인과 품질·비용을 검증 |
| 2026-09-18 | 확정된 요청 | 현 단계는 문서화만 수행 | 사용자가 구조·기술 선택·구현 계획만 요청 |
| 2026-09-18 | 제안 | 배경음 합성 설명을 "원음 전체를 그대로 섞지 않는다"로 정정 | 기존 문장이 원음 전체 혼합과 대사 중복 방지를 동시에 주장해 구현 시 반대로 읽힐 수 있었음. IMPLEMENTATION_PLAN 3단계 완료 기준과도 불일치 |
| 2026-09-18 | 제안 | `segments`를 `transcript_segments`(원본 소속)와 `translated_segments`(작업 소속)로 분리 | 원문과 번역문을 한 행에 두면 세그먼트가 대상 언어에 종속되어 언어 추가 시 원문이 복제됨. PROJECT_BRIEF의 STT 재사용 전제를 데이터 모델이 지키지 못했음 |
| 2026-09-18 | 제안 | 제작·게시 상태에 rejected/failed/cancelled를 추가하고 전이표를 명시 | 기존 상태 목록에 반려·실패·취소 경로가 없어 IMPLEMENTATION_PLAN 4단계의 반려 요구와 어긋났음. 단계 실행 상태에만 failed/cancelled가 있었음 |
| 2026-09-18 | 제안 | 더빙 길이 정합 규칙(허용 오차 ±10%, 속도 0.9~1.15배, 조정 순서) 추가 | 기존 설명이 "허용 범위"만 언급해 구간 겹침·자막 오차의 판정 기준이 없었음. 수치는 대표 영상 측정 전까지 제안값 |
| 2026-09-18 | 제안 | 게시 후 수정 경로와 게시 상태 superseded 추가 | 업로드된 영상은 파일을 교체할 수 없어 새 업로드 후 이전 영상 비공개 전환이 필요한데 설계에 경로가 없었음 |
| 2026-09-18 | 제안 | 입력 해시 구성 요소를 공급자·모델·음성·프롬프트·용어집·계약 버전으로 명시 | 구성이 불명확하면 모델을 바꿔도 과거 산출물이 재사용됨 |
| 2026-09-18 | 제안 | 장시간 단계를 단일 Celery 태스크로 실행하지 않는 규칙 추가 | Redis 재전달과 워커 재시작 시 중복 실행·유실 위험. 제출·조회·수거 분리로 DB가 진행 상태를 보유 |
| 2026-09-18 | 제안 | budgets 엔터티와 blocked 상태로 비용 상한 강제 지점 추가 | 사후 비용 기록만 있어 재시도 루프가 유료 API를 반복 호출할 수 있었음 |
| 2026-09-18 | 제안 | glossaries, voice_assignments 엔터티 추가 | 번역 용어집과 화자별 음성 배정을 저장할 위치가 없었음 |
| 2026-09-18 | 제안 | 미리보기 서명 URL 발급 주체를 API로 명시하고 구성도 수정 | 구성도가 저장소에서 화면으로 직행하는 것처럼 보여 인증 원칙과 어긋나 보였음 |
| 2026-09-18 | 확인 필요 | YouTube 쿼터를 처리량 제약으로 등록 | 업로드 호출 비용이 커 하루 편수가 제한될 수 있음. 공식 페이지를 이번 환경에서 열지 못해 수치는 기재하지 않음 |
| 2026-09-18 | 제안 | 테스트 전략 섹션 추가 | 완료 기준이 육안 검사에 가까워 회귀를 잡을 수 없었음 |
| 2026-09-18 | 제안 | 보존·삭제 정책과 파생물 연쇄 삭제 추가 | 대본에 개인정보가 포함될 수 있는데 삭제 시 파생물 처리 방침이 없었음 |
| 2026-09-18 | 제안 | 더빙 길이에 겹침 금지 조건을 허용 오차보다 우선하도록 추가 | 허용 오차만으로는 10초 구간에 11초 음성이 들어가 다음 대사와 겹칠 수 있었음 |
| 2026-09-18 | 제안 | 영상 교체 시 이전 영상이 공개 중이면 새 영상의 실제 공개 확인 후 전환 | 예약 성공만 확인하고 전환하면 예약 시각까지 두 영상 모두 공개되지 않는 공백이 생겼음 |
| 2026-09-18 | 제안 | budget_reservations로 예산 예약·정산 추가 | 누적액 확인만으로는 여러 워커가 같은 잔액을 동시에 사용해 한도를 넘을 수 있었음 |

향후 변경 시 날짜, 제안/확정 상태, 변경 내용, 근거, 영향받는 문서와 구현을 기록합니다.
