# Current Customer Interface Analysis

작성일: 2026-03-20

대상: veteran teammate

## 1. 문서 목적

이 문서는 현재 `backend` repo 기준으로 완성된 customer interface를 다시 분석한 보고서다.

이번 재작성에서는 기존 customer flow 분석에 더해 아래 변경사항을 함께 반영했다.

- `former / trend / current` 추천 구조 정리
- confirm 이후 admin handoff 가능한 session state 저장
- admin interface를 위한 backend contract 사전 준비
- 중간발표 자료 기준의 "웹페이지 구축 -> 서비스 배포 -> 모델 고도화" 방향 반영

## 2. 범위 정의

현재 repo 안에는 실제 customer-facing 프론트 코드가 없다.

즉 지금의 "customer interface 완성도"는 아래 두 층으로 해석해야 한다.

- 화면에 무엇을 보여줄지에 대한 정보 구조
- 그 화면을 작동시키는 backend API / DB 상태 전이

따라서 이 보고서는 렌더링 UI가 아니라, 고객 화면을 성립시키는 interface contract를 분석한다.

관련 핵심 파일:

- `mirrai_project/urls.py`
- `app/api/v1/urls_django.py`
- `app/api/v1/django_views.py`
- `app/api/v1/services_django.py`
- `app/models_django.py`
- `main.py`

## 3. 현재 customer interface 한 줄 판정

현재 customer interface는 "실제 시각 레이어는 미구현이지만, 고객이 밟게 될 주 흐름과 상태 제어는 backend 기준으로 프로토타입 완성 단계"다.

현재 연결된 흐름:

- 고객 존재 확인
- 회원가입
- 로그인
- 설문 제출
- 설문 skip
- 촬영 업로드
- 기존 스타일 조회
- 트렌드 조회
- 새 추천 5개 조회
- 스타일 확정
- 디자이너/관리자 전달

즉 사용자의 행동 흐름은 이어진다.

다만 아래는 아직 운영 수준이 아니다.

- 실제 프론트 화면
- 실제 생성 이미지
- production auth
- actual AI inference quality

## 4. customer interface 정보 구조

현재 customer interface는 backend 관점에서 4개 구간으로 나뉜다.

### 4-1. Auth 진입

지원 API:

- `POST /api/v1/auth/check/`
- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/login/`

역할:

- 기존 고객 여부 확인
- 신규 고객 등록
- 로그인 토큰 및 customer_id 반환

평가:

- customer entry point로는 충분하다.
- 다만 현재 token은 mock token이며 Django API 보호는 약하다.
- 따라서 "고객 흐름 연결" 목적에는 적합하지만 "실서비스 auth"로 보긴 어렵다.

### 4-2. 설문

지원 API:

- `POST /api/v1/survey/`

역할:

- 취향 데이터를 저장
- 20차원 one-hot `preference_vector` 생성

평가:

- recommendation scoring의 기반으로 정상 작동한다.
- admin report에서도 나중에 이 설문 snapshot을 활용할 수 있도록 구조가 확장됐다.

### 4-3. recommendation entry

추천 진입점은 이제 명확히 3갈래다.

- `former_recommendations`
- `trend`
- `current_recommendations`

이 분리는 customer interface 관점에서 가장 중요한 구조 개선이다.

#### former_recommendations

API:

- `GET /api/v1/analysis/former-recommendations/?customer_id=...`

의미:

- 과거에 생성되었고, 고객이 다시 참고할 수 있는 추천 이력

현재 규칙:

- `is_chosen` 항목 우선
- 이후 최신 이력으로 보충
- 최대 5개
- 최신 generated batch가 아직 미선택 상태라면 former에서는 숨김

UI 관점 장점:

- "기존 스타일"과 "방금 생성된 새 결과"가 섞이지 않는다.
- 고객이 실제로 골랐던 이력을 먼저 보여줄 수 있다.

#### trend

API:

- `GET /api/v1/analysis/trend/?days=30`

의미:

- 최근 기간 매장 인기 스타일

현재 규칙:

- `StyleSelection` 집계 기반
- 기본은 30일
- 데이터 부족 시 fallback catalog 반환

UI 관점 장점:

- 설문이나 촬영 없이도 고객에게 탐색 entry를 줄 수 있다.

주의:

- fallback 결과가 실제 trend처럼 보일 수 있으므로 프론트 배지 처리 여지는 남아 있다.

#### current_recommendations

API:

- `GET /api/v1/analysis/recommendations/?customer_id=...`

의미:

- 이번 촬영 기준 최신 generated batch 5개

현재 규칙:

- 최신 capture / face analysis / survey 시점 비교 후 필요하면 batch 재생성
- 설문이 없어도 capture가 있으면 얼굴 분석 기반으로 생성
- status-driven 응답

UI 관점 장점:

- `survey accept`
- `survey skip`

둘 다 같은 recommendation result 화면으로 연결 가능하다.

## 5. 상태 기반 UX 관점 분석

현재 customer interface에서 가장 의미 있는 개선은 response가 "데이터"만이 아니라 "화면 상태"를 제어한다는 점이다.

대표 status:

- `ready`
- `empty`
- `needs_input`
- `needs_capture`
- `success`

이 구조 덕분에 프론트는 에러 페이지보다 유도형 UX를 만들 수 있다.

예:

- 설문도 캡처도 없으면 `needs_input`
- 촬영이 없으면 `needs_capture`
- 과거 이력이 없으면 `empty`

veteran 관점에서 중요한 판단:

- 현재 customer interface API는 단순 CRUD가 아니라 stateful UI contract에 가깝다.
- 프론트는 status field를 기준으로 컴포넌트 분기하는 것이 맞다.

## 6. 카드 클릭 인터랙션 분석

요구사항상 카드 클릭 시 같은 페이지 안에서:

- sample image
- simulation image
- LLM explanation

을 detail component로 보여줘야 한다.

현재 recommendation payload는 그 요구를 거의 충족한다.

카드 단위 필드:

- `style_id`
- `style_name`
- `style_description`
- `sample_image_url`
- `simulation_image_url`
- `llm_explanation`
- `match_score`

판정:

- 별도 detail 조회 API 없이도 1차 구현 가능
- 썸네일 클릭 후 우측 detail panel을 같은 payload 내부 데이터로 렌더링할 수 있음

남은 과제:

- `simulation_image_url` 실제 파일 전략
- explanation이 실제 LLM output으로 치환될 시점 정의

## 7. confirm 이후 interface 의미

지원 API:

- `POST /api/v1/analysis/confirm/`
- `POST /api/v1/analysis/consult/`

현재 의미:

- `consult`는 `confirm` alias
- 고객이 선택한 결과가 recommendation history, selection log, consultation log로 함께 저장됨

현재 side effect:

1. `FormerRecommendation.is_chosen` 갱신
2. `StyleSelection` 생성
3. 기존 active consultation close
4. 새 `ConsultationRequest` 생성
5. `survey_snapshot`, `analysis_data_snapshot`, `selected_recommendation`, `source` 저장

customer interface 관점 의미:

- 고객의 선택이 그냥 끝나는 것이 아니라
- 이후 admin/partner 쪽에서 이어서 읽을 수 있는 구조로 변환된다

즉 confirm은 단순 버튼이 아니라 "customer interface -> admin interface handoff point"다.

## 8. admin-ready backend가 customer interface에 주는 영향

이번 변경으로 customer interface 보고서에 반드시 추가되어야 하는 부분은, customer flow가 이제 admin interface와 분리되지 않는다는 점이다.

현재 customer confirm 이후 생성되는 consultation/session state는 아래 admin 화면을 바로 지원할 수 있다.

- 관리자 대시보드
- 점내 고객 목록
- 고객 상세
- 고객 추천 리포트
- 디자이너 메모
- 상담 종료
- 주간 트렌드 리포트
- 스타일 리포트

이건 customer interface 관점에서 중요하다.

이유:

- 고객이 "선택 완료"를 누른 순간
- backend는 단순 로그 저장이 아니라
- 관리자 화면이 읽을 수 있는 active session을 만든다

즉 customer interface의 끝점이 admin 업무 흐름의 시작점으로 재구성됐다.

## 9. admin interface 미구현 상태에서의 readiness

관리자 UI는 아직 없지만, backend는 아래 수준까지 준비되었다.

- partner register/login 가능
- active customer session 조회 가능
- customer detail / latest survey / latest face analysis 조회 가능
- latest generated batch 및 final selected style 조회 가능
- 상담 note 저장 가능
- 상담 종료 가능
- 설문 snapshot 기반 주간 trend filter 가능
- style report / related style 추천 가능

따라서 현재 customer interface를 분석할 때는 더 이상 "customer 전용 proto"가 아니라:

`customer journey의 마지막 단계가 admin-ready session data로 자연스럽게 이어지는 구조`

로 봐야 한다.

## 10. 중간발표 자료와의 정합성

중간발표 초안에서 읽히는 방향은 다음과 같다.

- 웹페이지 구축
- 서비스 배포
- ControlNet 등 모델 고도화

현재 backend는 이 순서와 대체로 맞는다.

### 현재 이미 준비된 것

- 웹페이지가 붙을 수 있는 customer/admin API contract
- 상태 기반 recommendation flow
- admin handoff 가능한 session model
- internal AI service slot (`main.py`)

### 아직 후속인 것

- actual generative output
- ControlNet/SegFace/SAM2/Stable Diffusion 연동
- visual front implementation
- production auth and permission

따라서 veteran teammate에게는 이렇게 설명하는 게 맞다.

`지금은 customer/admin 화면을 붙일 backend 골격과 state machine이 정리된 단계이고, 발표자료의 모델 고도화는 그 위에 얹히는 다음 단계다.`

## 11. 실제로 아직 없는 것

이 부분은 계속 명확히 구분해야 한다.

### 11-1. 실제 customer-facing UI 코드 없음

- React / template / SPA 코드 없음
- 현재는 API와 상태 계약이 완성된 상태

### 11-2. actual generated image 없음

- `simulation_image_url`은 구조상 준비돼 있으나 placeholder 경로일 수 있음

### 11-3. actual AI inference 미완성

- face analysis placeholder
- recommendation generation rule-based
- `main.py`는 internal AI service shell

### 11-4. production auth 미완성

- customer / partner 모두 mock token 기반

## 12. 종합 판정

현재 customer interface는 backend 기준으로 아래 수준이다.

- customer flow는 프로토타입 완성 단계
- status-driven UI를 바로 만들 수 있는 상태
- former / trend / current 분리가 정리됨
- click detail payload가 준비됨
- confirm 이후 admin handoff 데이터가 남음
- admin interface 구축을 위한 backend contract가 사전 준비됨

즉 예전보다 한 단계 올라가서, 이제는 단순 customer demo API가 아니라:

`customer recommendation experience + admin handoff workflow를 함께 고려한 backend prototype`

로 평가하는 것이 맞다.

## 13. veteran teammate용 액션 포인트

1. 프론트는 `status` 기반 분기를 먼저 확정할 것
2. customer result card와 admin customer report가 같은 recommendation payload를 재사용하도록 맞출 것
3. fallback trend 여부를 UI에서 명시할지 결정할 것
4. generated image 저장 전략을 모델 팀과 합의할 것
5. customer token / partner token 보호 전략을 별도 작업으로 분리할 것
