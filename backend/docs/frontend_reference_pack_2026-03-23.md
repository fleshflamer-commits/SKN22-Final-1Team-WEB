# MirrAI Frontend Reference Pack

Created on 2026-03-23

This document is the quickest reference for the frontend side. It focuses on what to call, what to send, what comes back, and how to branch the UI.

## 1. Base URL

```text
/api/v1/
```

## 2. Authentication

Client API
- The current client flow uses `client_id` as the main identifier.
- The current client token format is `mock-token-*`.

Admin API
- Admin endpoints require `Authorization: Bearer <access_token>`.

## 3. Client API

| Feature | API | Required Input | Main Response |
|---|---|---|---|
| Check existing client | `POST /auth/check/` | `phone` | `is_existing`, `client_id` |
| Register client | `POST /auth/register/` | `name`, `gender`, `phone` | `status`, `client_id`, `access_token` |
| Log in client | `POST /auth/login/` | `phone` | `access_token`, `client_id` |
| Submit survey | `POST /survey/` | `client_id`, survey fields | `preference_vector`, `created_at` |
| Upload capture | `POST /capture/upload/` | `client_id`, `file` | `status`, `record_id`, `privacy_snapshot` |
| Check capture status | `GET /capture/status/` | `record_id` | `status`, `next_action`, `landmark_snapshot` |
| Get former recommendations | `GET /analysis/former-recommendations/` | `client_id` | `status`, `items` |
| Get current recommendations | `GET /analysis/recommendations/` | `client_id` | `status`, `items`, `next_action(s)` |
| Get trend recommendations | `GET /analysis/trend/` | optional `days`, optional `client_id` | `status`, `items` |
| Confirm style | `POST /analysis/confirm/` | `client_id` + `recommendation_id` or `style_id` | `consultation_id`, `selected_style_id` |
| Cancel style | `POST /analysis/cancel/` | `client_id` | `status=cancelled`, `next_action=client_input` |

## 4. Admin API

| Feature | API | Required Input | Main Response |
|---|---|---|---|
| Register admin | `POST /admin/auth/register/` | name, store info, phone, business number, password, required consent flags | `admin`, `access_token`, `expires_in` |
| Log in admin | `POST /admin/auth/login/` | `phone`, `password` | `admin`, `access_token`, `expires_in` |
| Get current admin | `GET /admin/auth/me/` | none | `admin` |
| Dashboard | `GET /admin/dashboard/` | none | `today_metrics`, `top_styles_today`, `active_clients_preview` |
| Active clients | `GET /admin/clients/active/` | none | `items` |
| All clients / search | `GET /admin/clients/?q=` | optional `q` | `items` |
| Client detail | `GET /admin/clients/detail/?client_id=` | `client_id` | `client`, `capture_history`, `notes` |
| Client recommendation report | `GET /admin/clients/recommendations/?client_id=` | `client_id` | `latest_generated_batch`, `final_selected_style` |
| Save consultation note | `POST /admin/consultations/note/` | `client_id`, `consultation_id`, `content` | `status`, `note_id` |
| Close consultation | `POST /admin/consultations/close/` | `consultation_id` | `status`, `consultation_id` |
| Trend report | `GET /admin/trend-report/` | optional `days`, optional filters | `kpi`, `ranking`, `distribution` |
| Style report | `GET /admin/style-report/?style_id=` | `style_id` | `style`, `related_styles` |

## 5. UI Status Guide

### Current recommendations

| status | Meaning | Frontend action |
|---|---|---|
| `needs_input` | Survey or capture data is missing | Show survey and capture CTA |
| `needs_capture` | A valid capture is still needed | Move to capture screen |
| `ready` | Recommendation cards are ready | Render recommendation cards |
| `empty` | No cards are available yet | Show guide text and retry CTA |

### Capture upload

| status | Meaning | Frontend action |
|---|---|---|
| `success` | Upload accepted | Save `record_id` and poll status |
| `needs_retake` | Face detection failed | Show retake guidance |

### Cancel flow

```json
{
  "status": "cancelled",
  "next_action": "client_input"
}
```

When this comes back, the frontend should move the user back to the client input step.

## 6. Request Examples

### Check existing client

```json
POST /api/v1/auth/check/
{
  "phone": "01012345678"
}
```

### Submit survey

```json
POST /api/v1/survey/
{
  "client_id": 1,
  "target_length": "medium",
  "target_vibe": "natural",
  "scalp_type": "normal",
  "hair_colour": "black",
  "budget_range": "5-10"
}
```

### Confirm style

Use `recommendation_id` whenever it is available.

```json
POST /api/v1/analysis/confirm/
{
  "client_id": 1,
  "recommendation_id": 31,
  "admin_id": 3,
  "source": "current_recommendations",
  "direct_consultation": false
}
```

### Cancel style

```json
POST /api/v1/analysis/cancel/
{
  "client_id": 1,
  "recommendation_id": 31,
  "source": "current_recommendations"
}
```

### Save admin note

```json
POST /api/v1/admin/consultations/note/
Authorization: Bearer <token>
{
  "client_id": 1,
  "consultation_id": 22,
  "content": "The client prefers a softer fringe line and lighter side volume."
}
```

## 7. Response Examples

### Current recommendations: `ready`

```json
{
  "status": "ready",
  "source": "current_recommendations",
  "batch_id": "uuid",
  "message": "The latest Top-5 recommendations were generated from the most recent capture and analysis.",
  "items": [
    {
      "recommendation_id": 31,
      "style_id": 204,
      "style_name": "Sleek Mini Bob",
      "sample_image_url": "/media/styles/204.jpg",
      "simulation_image_url": null,
      "image_policy": "vector_only",
      "can_regenerate_simulation": true,
      "reasoning_snapshot": {
        "summary": "face 40.0/40 | ratio 20.0/20 | preference 26.0/40"
      }
    }
  ]
}
```

### Capture result: `needs_retake`

```json
{
  "status": "needs_retake",
  "record_id": 15,
  "face_count": 0,
  "reason_code": "no_face_detected",
  "message": "No face was detected. Please look straight at the camera and retake the photo.",
  "next_action": "capture",
  "privacy_snapshot": {
    "storage_policy": "vector_only"
  }
}
```

## 8. Notes

- `simulation_image_url` can be `null` under the `vector_only` policy.
- `image_policy=vector_only` means the system did not persist a generated simulation asset.
- Admin APIs always require a Bearer token.
- `client_input` means "go back to the client input step after cancellation."
