## Context

The backend authenticates to Azure OpenAI using `CertificateCredential.get_token()` from `azure-identity`. In environments behind a corporate proxy (`dev`, `uat`, `prod`), the code temporarily sets `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` env vars around the `get_token()` call. However, `REQUESTS_CA_BUNDLE` is currently pointed at the single proxy certificate file (e.g., `cert/uat.cert`), which lacks the system CA certificates needed to verify Azure AD's TLS chain. This causes certificate verification failures.

The env-var save/restore logic is also inlined directly in `_AzureBearerAuth.auth_flow()`, making it harder to reuse or test.

## Goals / Non-Goals

**Goals:**
- Fix `get_token()` TLS verification by building a combined CA bundle (system CAs + proxy certs)
- Extract proxy env-var scoping into a clean, reusable context manager
- Keep proxy scoping behavior identical: env vars set only during `get_token()`, restored immediately after

**Non-Goals:**
- Changing the httpx client's `proxy` kwarg structure (that works correctly today)
- Supporting proxy for non-Azure HTTP calls (tools should bypass proxy)
- Changing certificate storage or retrieval from AWS Secrets Manager

**Note:** The httpx client's `verify` kwarg (line 110) has the same root-cause bug — it also points to the single proxy cert. This is fixed implicitly because `proxy_cert` is reassigned to the combined bundle path before being passed to both `_AzureBearerAuth` and `http_kwargs["verify"]`.

## Decisions

### 1. Build combined CA bundle using certifi + cert directory

**Decision:** At startup, read the `certifi` default CA bundle, append all `.cert`/`.crt`/`.pem` files from the configured cert directory (derived from `cloud_proxy_cert` path), and write the combined result to a temp file.

**Rationale:** MSAL's underlying `requests` library uses `REQUESTS_CA_BUNDLE` to verify TLS. When this points to only the proxy cert, it can't verify the Azure AD endpoint. By combining system CAs with proxy certs, both the proxy TLS and the upstream Azure AD TLS chains are verifiable.

**Alternatives considered:**
- Setting `REQUESTS_CA_BUNDLE` to the system certifi bundle and ignoring proxy cert — wouldn't work if proxy uses a private CA.
- Using `SSL_CERT_FILE` instead — same problem, and less portable across libraries.
- Configuring `requests.Session` with a custom adapter — too invasive, and `get_token()` doesn't expose session hooks.

### 2. Context manager for scoped proxy env vars

**Decision:** Create a `proxy_env()` context manager that accepts `proxy_url` and `ca_bundle_path`, sets `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE`, and restores originals on exit via `try/finally`.

**Rationale:** The current inline save/restore logic in `auth_flow` is correct but verbose and not reusable. A context manager is the idiomatic Python pattern for temporary state scoping, is easier to test, and reads more clearly.

### 3. Derive cert directory from `cloud_proxy_cert` setting

**Decision:** Use `Path(settings.cloud_proxy_cert).parent` as the cert directory to scan for additional certs. This reuses the existing config without adding new settings.

**Rationale:** The cert directory already contains the proxy certs. No config changes needed.

## Risks / Trade-offs

- **[Temp file lifecycle]** → The combined CA bundle temp file lives for the process lifetime. This is acceptable since it's small (~300KB) and matches the existing pattern for the PEM temp file.
- **[Cert directory contents]** → All `.cert`/`.crt`/`.pem` files in the directory are appended. If unexpected files exist there, they'd be included. → Mitigation: the cert directory is controlled infrastructure, not user-writable.
- **[Thread safety of env vars]** → `os.environ` mutations are not thread-safe. → Mitigation: unchanged from current behavior; `get_token()` is synchronous and the scoping window is minimal. Python's GIL further reduces practical risk.
