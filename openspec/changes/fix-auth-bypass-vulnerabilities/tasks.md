## 1. Research Endpoint Auth

- [x] 1.1 Add `Depends(get_current_user)` to `POST /api/research` in `routers/research.py:56`
- [x] 1.2 Add `Depends(get_current_user)` to `POST /api/research/async` in `routers/research.py:166`
- [x] 1.3 Add `Depends(get_current_user)` to `POST /api/research/clarify/{id}` in `routers/research.py:26`
- [x] 1.4 Add `Depends(get_current_user)` to `GET /api/research/jobs/{id}` in `routers/research.py:187`
- [ ] 1.5 Add ownership check to async job status — user can only view their own jobs (requires DB schema change to add owner_sid to research_jobs table — deferred)
- [x] 1.6 Write test: unauthenticated research request returns 401

## 2. Session Endpoint Auth

- [x] 2.1 Add `Depends(get_current_user)` to `POST /api/sessions/{id}/share` in `routers/sessions.py:115`
- [x] 2.2 Add ownership check — only session owner can share
- [x] 2.3 Add `Depends(get_current_user)` to `DELETE /api/sessions/{id}/share` in `routers/sessions.py:127`
- [x] 2.4 Change `PATCH /api/sessions/{id}` from `get_optional_user` to `get_current_user` + ownership check
- [x] 2.5 Change `DELETE /api/sessions/{id}` from `get_optional_user` to `get_current_user` + ownership check
- [x] 2.6 Write test: unauthenticated session share returns 401
- [x] 2.7 Write test: non-owner session delete returns 403

## 3. Document Upload Auth

- [x] 3.1 Add `Depends(get_current_user)` to `POST /api/documents/upload` in `routers/documents.py:16`
- [x] 3.2 Write test: unauthenticated upload returns 401

## 4. JWT Secret Validation

- [x] 4.1 Add startup check in `main.py` — if `jwt_secret == "change-me-in-prod"` and not in dev mode, log critical warning or refuse to start
- [x] 4.2 Write test: app startup with default secret in prod mode raises error
