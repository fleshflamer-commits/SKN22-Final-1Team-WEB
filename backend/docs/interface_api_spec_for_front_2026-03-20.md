# MirrAI Interface API Spec

작성일: 2026-03-20

대상: veteran teammate

## 1. 문서 목적

이 문서는 현재 `backend` repo 기준으로, 고객용 interface와 향후 관리자 interface가 붙을 수 있도록 정리된 API contract를 명세 형태로 정리한 것이다.

범위:

- customer-facing API
- admin-ready API
- 공통 상태 규약
- DB 상태 전이 관점의 의미

전제:

- 실제 프론트 렌더링 코드는 이 repo에 없다.
- 따라서 본 문서는 화면 명세서와 연결되는 backend contract 문서로 봐야 한다.

## 2. Base Path

모든 Django API 기준 base path:

`/api/v1/`

FastAPI internal AI service:

- root: `main.py`
- internal path: `/internal/*`

## 3. 공통 응답 규약

recommendation 계열 응답은 status-driven 구조를 따른다.

대표 status:

- `ready`
- `empty`
- `needs_input`
- `needs_capture`
- `success`

화면 분기 원칙:

- `ready`: 결과 렌더링
- `empty`: 빈 상태 안내 + 대체 CTA
- `needs_input`: 설문/촬영 유도
- `needs_capture`: 캡처 유도
- `success`: 저장/전송 완료 토스트 또는 완료 화면 전환

## 4. Customer API

### 4-1. 고객 존재 확인

`POST /api/v1/auth/check/`

request:

```json
{
  "phone": "01012345678"
}
```

response:

```json
{
  "is_existing": true,
  "name": "홍길동",
  "gender": "F",
  "customer_id": 1
}
```

또는

```json
{
  "is_existing": false
}
```

### 4-2. 고객 회원가입

`POST /api/v1/auth/register/`

request:

```json
{
  "name": "홍길동",
  "gender": "F",
  "phone": "01012345678"
}
```

response:

```json
{
  "status": "success",
  "customer_id": 1,
  "access_token": "mock-token-1",
  "token_type": "bearer"
}
```

주의:

- 현재 token은 mock token이다.
- 실제 auth protection은 아직 production-ready가 아니다.

### 4-3. 고객 로그인

`POST /api/v1/auth/login/`

request:

```json
{
  "phone": "01012345678"
}
```

response:

```json
{
  "access_token": "mock-token-1",
  "token_type": "bearer",
  "customer_id": 1
}
```

### 4-4. 설문 저장

`POST /api/v1/survey/`

request:

```json
{
  "customer_id": 1,
  "target_length": "단발",
  "target_vibe": "시크",
  "scalp_type": "직모",
  "hair_colour": "흑발",
  "budget_range": "5만~10만"
}
```

response:

```json
{
  "id": 1,
  "customer": 1,
  "target_length": "단발",
  "target_vibe": "시크",
  "scalp_type": "직모",
  "hair_colour": "흑발",
  "budget_range": "5만~10만",
  "preference_vector": [0, 1, ...],
  "created_at": "..."
}
```

설명:

- 설문은 20차원 one-hot 기반 `preference_vector`로 저장된다.

### 4-5. 캡처 업로드

`POST /api/v1/capture/upload/`

request:

- `multipart/form-data`
- fields:
  - `customer_id`
  - `file`

response:

```json
{
  "status": "success",
  "record_id": 10
}
```

설명:

- 업로드 후 background pipeline이 `FaceAnalysis`와 generated recommendation batch를 생성한다.

### 4-6. 기존 스타일 조회

`GET /api/v1/analysis/former-recommendations/?customer_id=1`

response example:

```json
{
  "status": "ready",
  "source": "former_recommendations",
  "items": [
    {
      "recommendation_id": 21,
      "batch_id": "uuid",
      "source": "generated",
      "style_id": 204,
      "style_name": "Sleek Mini Bob",
      "style_description": "...",
      "sample_image_url": "/media/styles/204.jpg",
      "simulation_image_url": "/media/synthetic/1_204.jpg",
      "llm_explanation": "...",
      "match_score": 100.0,
      "rank": 1,
      "is_chosen": true,
      "created_at": "..."
    }
  ]
}
```

정렬 규칙:

- `is_chosen DESC`
- `chosen_at DESC`
- `created_at DESC`
- 최대 5개

### 4-7. 새 추천 5개 조회

`GET /api/v1/analysis/recommendations/?customer_id=1`

status branch:

- `needs_input`
- `needs_capture`
- `ready`

`needs_input` example:

```json
{
  "status": "needs_input",
  "source": "current_recommendations",
  "message": "아직 취향을 알려주지 않으셨어요. 설문을 진행하거나 바로 촬영을 시작해주세요.",
  "next_actions": ["survey", "capture"],
  "items": []
}
```

`ready` example:

```json
{
  "status": "ready",
  "source": "current_recommendations",
  "batch_id": "uuid",
  "message": "최신 촬영 데이터를 기준으로 새 시뮬레이션 5개를 불러왔어요.",
  "items": [
    {
      "recommendation_id": 31,
      "style_id": 204,
      "style_name": "Sleek Mini Bob",
      "sample_image_url": "/media/styles/204.jpg",
      "simulation_image_url": "/media/synthetic/1_204.jpg",
      "llm_explanation": "...",
      "match_score": 100.0,
      "rank": 1
    }
  ]
}
```

설명:

- `recommendations`는 현재 "과거 시뮬레이션"이 아니라 "이번 촬영 기준 최신 5개"를 의미한다.
- 설문이 없어도 capture가 있으면 얼굴 분석 기반으로 batch를 만든다.

### 4-8. 트렌드 조회

`GET /api/v1/analysis/trend/?days=30`

response:

```json
{
  "status": "ready",
  "source": "trend",
  "days": 30,
  "items": [
    {
      "source": "trend",
      "style_id": 201,
      "style_name": "Side-Parted Lob",
      "sample_image_url": "/media/styles/201.jpg",
      "llm_explanation": "...",
      "match_score": 12.0,
      "rank": 1
    }
  ]
}
```

설명:

- 최근 `days` 기간의 `StyleSelection` 집계 기반이다.
- 데이터 부족 시 fallback catalog를 반환한다.

### 4-9. 선택 확정 / 관리자 전달

`POST /api/v1/analysis/confirm/`

request:

```json
{
  "customer_id": 1,
  "recommendation_id": 31,
  "source": "current_recommendations",
  "direct_consultation": false
}
```

또는 trend 선택:

```json
{
  "customer_id": 1,
  "style_id": 201,
  "source": "trend",
  "direct_consultation": false
}
```

response:

```json
{
  "status": "success",
  "consultation_id": 8,
  "selected_style_id": 204,
  "selected_style_name": "Sleek Mini Bob",
  "source": "current_recommendations",
  "direct_consultation": false,
  "recommendation_id": 31,
  "message": "선택한 스타일과 분석 결과를 디자이너에게 전달했습니다."
}
```

side effects:

- `FormerRecommendation.is_chosen` 갱신
- `StyleSelection` 생성
- `ConsultationRequest` 생성
- `survey_snapshot`, `analysis_data_snapshot`, `selected_recommendation` 저장
- 기존 active consultation은 close 처리

### 4-10. 상담 요청 alias

`POST /api/v1/analysis/consult/`

설명:

- 현재 `confirm`과 동일 동작 alias다.

## 5. Admin-ready API

현재 admin UI는 미구현이지만, 아래 API는 화면설계서 기준으로 준비됐다.

### 5-1. 관리자 회원가입

`POST /api/v1/admin/auth/register/`

request:

```json
{
  "name": "Owner Kim",
  "store_name": "MirrAI Salon",
  "role": "owner",
  "phone": "01011112222",
  "business_number": "123-45-67890",
  "password": "pw1234!!"
}
```

response:

```json
{
  "status": "success",
  "partner_id": 1,
  "access_token": "mock-partner-token-1",
  "token_type": "bearer"
}
```

### 5-2. 관리자 로그인

`POST /api/v1/admin/auth/login/`

request:

```json
{
  "phone": "01011112222",
  "password": "pw1234!!"
}
```

response:

```json
{
  "status": "success",
  "partner_id": 1,
  "partner_name": "Owner Kim",
  "store_name": "MirrAI Salon",
  "access_token": "mock-partner-token-1",
  "token_type": "bearer"
}
```

### 5-3. 관리자 대시보드

`GET /api/v1/admin/dashboard/`

response shape:

```json
{
  "status": "ready",
  "ai_engine": {
    "status": "fallback",
    "mode": "local",
    "message": "...",
    "checked_at": "..."
  },
  "today_metrics": {
    "unique_visitors": 3,
    "active_customers": 1,
    "pending_consultations": 1,
    "confirmed_styles": 2
  },
  "top_styles_today": [],
  "active_customers_preview": []
}
```

대응 화면:

- `관리 페이지`
- `시스템 가용성 모니터링`
- `금일 점내 고객`
- `실시간 인기 스타일`

### 5-4. 점내 고객 목록

`GET /api/v1/admin/customers/active/`

response item shape:

```json
{
  "consultation_id": 1,
  "customer_id": 1,
  "customer_name": "Customer A",
  "phone": "01033334444",
  "status": "PENDING",
  "has_unread_consultation": true,
  "selected_style_name": "Sleek Mini Bob",
  "recommendation_count": 5,
  "last_activity_at": "..."
}
```

대응 화면:

- `점내 고객`

### 5-5. 전체 고객 목록 / 검색

`GET /api/v1/admin/customers/`

optional query:

- `q`

response item shape:

```json
{
  "customer_id": 1,
  "name": "Customer A",
  "gender": "F",
  "phone": "01033334444",
  "created_at": "...",
  "last_consulted_at": "...",
  "has_active_consultation": true
}
```

대응 화면:

- `전체 고객`
- `전체 고객; 검색`

### 5-6. 고객 상세

`GET /api/v1/admin/customers/detail/?customer_id=1`

response includes:

- customer basic info
- latest survey
- latest analysis
- active consultation
- saved notes

대응 화면:

- `고객 상세`

### 5-7. 고객 추천 리포트

`GET /api/v1/admin/customers/recommendations/?customer_id=1`

response includes:

- latest survey
- latest analysis
- final selected style
- latest generated batch 5개

대응 화면:

- `고객 추천`

### 5-8. 디자이너 메모 저장

`POST /api/v1/admin/consultations/note/`

request:

```json
{
  "customer_id": 1,
  "consultation_id": 8,
  "partner_id": 1,
  "content": "컷 전 모발 방향성 체크 필요"
}
```

response:

```json
{
  "status": "success",
  "note_id": 1,
  "consultation_id": 8,
  "message": "고객 관찰 메모가 저장되었습니다."
}
```

side effects:

- note row 생성
- consultation `is_read=True`
- consultation `status=IN_PROGRESS`

### 5-9. 상담 종료

`POST /api/v1/admin/consultations/close/`

request:

```json
{
  "consultation_id": 8
}
```

response:

```json
{
  "status": "success",
  "consultation_id": 8,
  "customer_id": 1,
  "message": "상담 세션이 종료되었습니다."
}
```

side effects:

- `is_active=False`
- `is_read=True`
- `status=CLOSED`
- `closed_at` 기록

### 5-10. 관리자 트렌드 리포트

`GET /api/v1/admin/trend-report/`

optional query:

- `days`
- `target_length`
- `target_vibe`
- `scalp_type`
- `hair_colour`
- `budget_range`

response shape:

```json
{
  "status": "ready",
  "days": 7,
  "filters": {
    "target_vibe": "시크"
  },
  "kpi": {
    "unique_customers": 1,
    "total_confirmations": 2,
    "active_consultations": 1
  },
  "ranking": [],
  "distribution": []
}
```

대응 화면:

- `트렌드 리포트`

설명:

- 필터는 `StyleSelection.survey_snapshot` 기준으로 동작한다.
- 화면설계서의 다차원 키워드 필터링과 주간 리포트 요구를 backend에서 먼저 받을 수 있게 한 상태다.

### 5-11. 스타일 리포트

`GET /api/v1/admin/style-report/?style_id=204&days=7`

response shape:

```json
{
  "status": "ready",
  "style": {
    "style_id": 204,
    "style_name": "Sleek Mini Bob",
    "image_url": "/media/styles/204.jpg",
    "description": "...",
    "keywords": ["mini bob", "sleek", "clean"],
    "recent_selection_count": 1,
    "chosen_count": 1
  },
  "related_styles": []
}
```

대응 화면:

- `스타일 리포트`

## 6. Internal AI Service Spec

`main.py`는 현재 customer/admin UI를 직접 서빙하지 않고 internal AI service 역할을 가진다.

### 6-1. Health

`GET /internal/health`

### 6-2. Face analysis

`POST /internal/analyze-face`

### 6-3. Simulation batch generation

`POST /internal/generate-simulations`

### 6-4. Style explanation

`POST /internal/explain-style`

설명:

- Django는 `MIRRAI_AI_SERVICE_URL`이 있을 때 이 service를 호출할 수 있다.
- 없으면 local fallback으로 동작한다.

## 7. 핵심 DB 상태 전이

### customer confirm 시

1. `FormerRecommendation.is_chosen` 갱신
2. `StyleSelection` 생성
3. 기존 active `ConsultationRequest` close
4. 새 `ConsultationRequest` 생성

### admin note 저장 시

1. `CustomerSessionNote` 생성
2. 해당 consultation `is_read=True`
3. consultation `status=IN_PROGRESS`

### admin close 시

1. `ConsultationRequest.is_active=False`
2. `status=CLOSED`
3. `closed_at` 기록

## 8. 현재 한계

- customer/admin 모두 mock token 기반
- 권한 검증 미약
- generated image는 placeholder path일 수 있음
- actual AI inference는 placeholder/fallback 기반
- admin UI 렌더링 코드는 아직 없음

## 9. veteran용 요약

현재 backend는 단순 API 모음이 아니라:

- customer recommendation flow를 상태 기반으로 제어하고
- confirm 이후 관리자 콘솔이 읽을 수 있는 세션 데이터를 남기며
- admin 화면설계서의 핵심 컴포넌트를 미리 받을 수 있는 contract를 제공하는

프로토타입 API 레이어까지는 준비된 상태다.
