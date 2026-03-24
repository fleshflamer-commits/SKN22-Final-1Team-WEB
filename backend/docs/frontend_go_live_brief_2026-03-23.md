# MirrAI Frontend Go-Live Brief

Created on 2026-03-23

This is the shortest checklist for starting frontend integration.

## What to do first

1. Split the screens into client flow and admin flow.
2. Map one API to each screen.
3. Handle `status`, `next_action`, and `next_actions` before polishing the UI.
4. Treat `null` image values as a normal case under the current storage policy.
5. Add the Bearer token to every admin API call.

## Response rules

- Client recommendations branch into `needs_input`, `needs_capture`, `ready`, and `empty`.
- Capture upload returns either `success` or `needs_retake`.
- Cancel flow returns `next_action=client_input`.
- When a recommendation card has `recommendation_id`, use that value first on confirm.
- Under the `vector_only` policy, `simulation_image_url` can be `null`.

## Modules to build first

- `clientApi`
- `captureApi`
- `recommendationApi`
- `adminApi`

## Screens to verify first

Client flow
- Login / register
- Survey
- Capture
- Recommendations
- Confirm / cancel

Admin flow
- Login / register
- Dashboard
- Active clients
- All clients
- Client detail
- Trend report
- Style report

## Final note

The frontend does not need to guess backend behavior anymore. It should be able to start from the contract and the example payloads directly.
