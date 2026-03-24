# MirrAI Backend Contract Handoff

Created on 2026-03-23

This document explains the current Django-first backend contract for the frontend team. It focuses on the actual runtime behavior, not on old planning terminology.

## 1. What the frontend needs first

The frontend does not need every backend implementation detail. It mainly needs these five things:

1. Which API belongs to which screen
2. Which request fields are required
3. What a successful response looks like
4. What `status`, `next_action`, and `next_actions` mean
5. Which rules apply to authentication and image handling

## 2. Current stack

- Main backend: Django + DRF
- Base API path: `/api/v1/`
- Internal AI service: `main.py` with `/internal/*`

## 3. Storage policy

The current default policy is `vector_only`.

- Client capture images are not persisted by default.
- The backend stores `landmark_snapshot`, analysis results, survey vectors, and recommendation regeneration snapshots.
- Legacy asset persistence is only enabled when `MIRRAI_PERSIST_CAPTURE_IMAGES=True`.

The recommendation history follows the same policy.

- Newly created recommendation rows do not persist generated simulation assets.
- They store `regeneration_snapshot` instead.
- The frontend can still display `sample_image_url`, while `simulation_image_url` may be `null`.

## 4. State values

### Current recommendations

`GET /api/v1/analysis/recommendations/` can return these states:

- `needs_input`
- `needs_capture`
- `ready`
- `empty`

`empty` means the backend could not prepare cards yet.

### Capture upload

- `success`
- `needs_retake`

### Capture status

- `pending`
- `processing`
- `done`
- `needs_retake`
- `failed`

### Cancel flow

- `status=cancelled`
- `next_action=client_input`

This means "the selected style was cancelled and the UI can return to the client input step."

## 5. Client API

| Feature | API | Frontend meaning |
|---|---|---|
| Check existing client | `POST /api/v1/auth/check/` | Branch between existing-client flow and new registration |
| Register client | `POST /api/v1/auth/register/` | Save returned `client_id` |
| Log in client | `POST /api/v1/auth/login/` | Save returned `client_id` |
| Submit survey | `POST /api/v1/survey/` | Move toward capture or recommendation flow |
| Upload capture | `POST /api/v1/capture/upload/` | Save `record_id` and poll capture status |
| Check capture status | `GET /api/v1/capture/status/` | Branch UI with `status` and `next_action` |
| Get former recommendations | `GET /api/v1/analysis/former-recommendations/` | Show past recommendation cards |
| Get current recommendations | `GET /api/v1/analysis/recommendations/` | Handle `needs_input / needs_capture / ready / empty` |
| Get trend recommendations | `GET /api/v1/analysis/trend/` | Show trend recommendation cards |
| Confirm style | `POST /api/v1/analysis/confirm/` | Hand the selected style off to the admin flow |
| Cancel style | `POST /api/v1/analysis/cancel/` | Return to the client input step |

## 6. Admin API

Admin APIs require `Authorization: Bearer <token>`.

| Feature | API | Frontend meaning |
|---|---|---|
| Register admin | `POST /api/v1/admin/auth/register/` | Save returned token |
| Log in admin | `POST /api/v1/admin/auth/login/` | Save returned token |
| Get current admin | `GET /api/v1/admin/auth/me/` | Validate token and load admin profile |
| Dashboard | `GET /api/v1/admin/dashboard/` | Show KPI and top-style summary |
| Active clients | `GET /api/v1/admin/clients/active/` | Show ongoing consultation sessions |
| All clients / search | `GET /api/v1/admin/clients/?q=` | Drive list and search screens |
| Client detail | `GET /api/v1/admin/clients/detail/?client_id=` | Show survey, analysis, captures, notes |
| Client recommendation report | `GET /api/v1/admin/clients/recommendations/?client_id=` | Show latest batch and final selected style |
| Save consultation note | `POST /api/v1/admin/consultations/note/` | Save note and update consultation state |
| Close consultation | `POST /api/v1/admin/consultations/close/` | Close consultation and refresh the list |
| Trend report | `GET /api/v1/admin/trend-report/` | Show ranking and distribution by period/filter |
| Style report | `GET /api/v1/admin/style-report/?style_id=` | Show single-style report details |

## 7. B2B scope

When `admin_id` is passed during style confirmation, the consultation is linked to that admin.

- The client confirmation API can optionally receive `admin_id`.
- Admin note and close actions use the authenticated admin (`request.user`) as the current scope.
- Dashboard, active sessions, and reports are scoped as far as the current admin-linked data allows.

In practice, this means admin scoping becomes clearer when the frontend sends `admin_id` on the confirmation handoff.

## 8. Fields the frontend should use immediately

Recommendation card
- `recommendation_id`
- `style_id`
- `style_name`
- `style_description`
- `keywords`
- `sample_image_url`
- `simulation_image_url`
- `llm_explanation`
- `reasoning`
- `reasoning_snapshot`
- `match_score`
- `rank`
- `image_policy`
- `can_regenerate_simulation`

Capture status
- `record_id`
- `status`
- `face_count`
- `error_note`
- `landmark_snapshot`
- `privacy_snapshot`
- `image_storage_policy`
- `next_action`

Admin client detail
- `client`
- `latest_survey`
- `latest_analysis`
- `capture_history`
- `analysis_history`
- `style_selection_history`
- `chosen_recommendation_history`
- `active_consultation`
- `notes`

## 9. Beginner summary

If the frontend is just starting, build these four modules first:

- `clientApi`
- `captureApi`
- `recommendationApi`
- `adminApi`

Then wire the screen branching with `status`, `next_action`, and `next_actions`.

## 10. Open checks for frontend sync

- Which exact screen route should `client_input` map to
- Whether `needs_input` should show survey or capture first
- Whether confirmation without `recommendation_id` will still be allowed in the final UI
- How the UI should present a `null` image under the `vector_only` policy
