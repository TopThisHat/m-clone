## Why

Multiple API endpoints are completely unauthenticated, allowing any user (or bot) to trigger research, upload documents, share/modify/delete sessions, and submit background jobs with webhook callbacks (SSRF risk). The default JWT secret is `"change-me-in-prod"` which enables session forgery if .env is not configured.

## What Changes

- Add `Depends(get_current_user)` to all research endpoints: `POST /api/research`, `POST /api/research/async`, `POST /api/research/clarify/{id}`, `GET /api/research/jobs/{id}`
- Add `Depends(get_current_user)` + ownership check to session share endpoints: `POST /api/sessions/{id}/share`, `DELETE /api/sessions/{id}/share`
- Change session PATCH/DELETE from `get_optional_user` to `get_current_user` + ownership validation
- Add `Depends(get_current_user)` to `POST /api/documents/upload`
- Fail startup if `jwt_secret` is the default value in production mode

## Capabilities

### New Capabilities
- `endpoint-auth-enforcement`: All mutating and resource-consuming endpoints require authentication and ownership validation

### Modified Capabilities

## Impact

- **Research endpoints** (`routers/research.py`): All 4 endpoints need auth added
- **Session endpoints** (`routers/sessions.py`): share/unshare need auth, PATCH/DELETE need ownership check
- **Document endpoint** (`routers/documents.py`): upload needs auth
- **Config** (`config.py`): JWT secret validation on startup
- **Frontend**: May need to handle 401 responses on endpoints that previously never returned them
