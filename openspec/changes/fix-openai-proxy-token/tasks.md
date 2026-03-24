## 1. Combined CA Bundle Builder

- [x] 1.1 Create `build_combined_ca_bundle(cert_dir: Path) -> str` function in `openai_factory.py` that reads `certifi.where()`, appends all `.cert`/`.crt`/`.pem` files from `cert_dir`, writes to a `NamedTemporaryFile(delete=False)`, and returns the temp file path. Falls back to `certifi.where()` if cert_dir doesn't exist or has no cert files.
- [x] 1.2 Call `build_combined_ca_bundle()` in `_build_azure_client()` when proxy is configured, using `Path(settings.cloud_proxy_cert).parent` as the cert directory. Pass the resulting path as `proxy_cert` instead of `settings.cloud_proxy_cert`.

## 2. Proxy-Scoped Context Manager

- [x] 2.1 Create a `proxy_env(proxy_url: str | None, ca_bundle: str | None)` context manager in `openai_factory.py` that saves/sets/restores `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` env vars in a `try/finally` block. No-ops when `proxy_url` is `None`.
- [x] 2.2 Refactor `_AzureBearerAuth.auth_flow()` to use `proxy_env()` context manager instead of inline env-var manipulation.

## 3. Verification

- [x] 3.1 Ensure `certifi` is listed as an explicit dependency in `pyproject.toml` (may already be transitive).
- [x] 3.2 Verify the httpx client's `verify` kwarg still uses the combined CA bundle path (not the old single-cert path).
