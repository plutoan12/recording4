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

## 변경 기록

| 날짜 | 상태 | 내용 | 이유 |
|---|---|---|---|
| 2026-09-18 | 제안 | Python API·워커 + 객체 저장소 + PostgreSQL | 영상 처리와 상태 관리를 분리 |
| 2026-09-18 | 제안 | 외부 AI API 우선, 립싱크는 확장 단계 | 먼저 기본 파이프라인과 품질·비용을 검증 |
| 2026-09-18 | 확정된 요청 | 현 단계는 문서화만 수행 | 사용자가 구조·기술 선택·구현 계획만 요청 |
| 2026-09-18 | 제안 | 배경음 합성 설명을 "원음 전체를 그대로 섞지 않는다"로 정정 | 기존 문장이 원음 전체 혼합과 대사 중복 방지를 동시에 주장해 구현 시 반대로 읽힐 수 있었음. IMPLEMENTATION_PLAN 3단계 완료 기준과도 불일치 |
| 2026-09-18 | 제안 | `segments`를 `transcript_segments`(원본 소속)와 `translated_segments`(작업 소속)로 분리 | 원문과 번역문을 한 행에 두면 세그먼트가 대상 언어에 종속되어 언어 추가 시 원문이 복제됨. PROJECT_BRIEF의 STT 재사용 전제를 데이터 모델이 지키지 못했음 |
| 2026-09-18 | 제안 | 제작·게시 상태에 rejected/failed/cancelled를 추가하고 전이표를 명시 | 기존 상태 목록에 반려·실패·취소 경로가 없어 IMPLEMENTATION_PLAN 4단계의 반려 요구와 어긋났음. 단계 실행 상태에만 failed/cancelled가 있었음 |

향후 변경 시 날짜, 제안/확정 상태, 변경 내용, 근거, 영향받는 문서와 구현을 기록합니다.
