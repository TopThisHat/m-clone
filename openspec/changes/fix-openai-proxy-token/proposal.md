## Why

The Azure token retrieval (`get_token()`) fails when going through the corporate proxy because `REQUESTS_CA_BUNDLE` is set to only the proxy certificate file (`cert/uat.cert`), not a full CA bundle. MSAL/requests needs the system CA certificates to verify Azure AD's TLS chain, plus the proxy cert appended. Without the system CAs, the TLS handshake to `login.microsoftonline.com` fails with a certificate verification error.

## What Changes

- Build a combined CA bundle at startup by appending all certificate files from the configured cert directory onto the system `certifi` CA bundle, writing the result to a temp file.
- Extract the proxy env-var scoping logic into a reusable context manager that sets/restores `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` around any block of code.
- Use this context manager in `_AzureBearerAuth.auth_flow()` for the `get_token()` call.

## Capabilities

### New Capabilities
- `proxy-scoped-context`: A context manager that temporarily applies `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` env vars and restores originals on exit, plus a startup helper that builds a combined CA bundle from certifi + proxy cert directory.

### Modified Capabilities

## Impact

- `backend/app/openai_factory.py` — refactor `_AzureBearerAuth.auth_flow()` to use the new context manager and combined CA bundle instead of raw env-var manipulation with the single proxy cert.
- New dependency: `certifi` (already present transitively via `httpx`/`requests`; may need explicit addition to `pyproject.toml`).
- No API changes, no frontend impact, no database changes.
