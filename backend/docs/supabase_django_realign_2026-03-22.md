# MirrAI Supabase + Django Realign Notes

## What Changed
- Active runtime now points to Django routes in `app.api.v1.urls_django`.
- `api/` is no longer the main entry path. It is left on disk as a backup reference for the planned frontend-based rewrite.
- Django template shells were added so the frontend team can bind to stable pages before the final UI lands.
- Database settings are now Supabase-ready through `SUPABASE_DB_URL` and `DATABASE_URL`.
- Capture storage can move from local `storage/` to Supabase Storage by turning on `SUPABASE_USE_REMOTE_STORAGE=True`.

## Current Runtime Shape
- Client and admin APIs: Django
- Front scaffold pages: Django templates
- AI analysis/generation: `main.py` FastAPI internal service

## Table-Centered Direction
Current Django models already map cleanly to relational tables:

- `clients`
- `admin_accounts`
- `surveys`
- `capture_records`
- `face_analyses`
- `styles`
- `former_recommendations`
- `style_selections`
- `consultation_requests`
- `client_session_notes`

This means the backend is already aligned with a Supabase/PostgreSQL-style table structure.

## What To Do When The Frontend Structure Arrives
1. Keep `app/api/v1` as the stable backend contract layer.
2. Replace the template shells page by page with the frontend team's structure.
3. Point `DATABASE_URL` to Supabase Postgres.
4. Turn on `SUPABASE_USE_REMOTE_STORAGE=True` when the bucket is ready.
5. Leave `main.py` as the internal AI service unless the team decides to merge that role back into Django.

## What Was Intentionally Not Done Yet
- No live Supabase migration was executed because project credentials were not provided.
- No GitHub origin reset was touched.
- Legacy `api/` files were not deleted because the team memo implies a backup-first rewrite after the frontend structure is finalized.

