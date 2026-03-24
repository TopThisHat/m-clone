## ADDED Requirements

### Requirement: Combined CA bundle builder
The system SHALL build a combined CA bundle at startup by concatenating the default `certifi` CA bundle with all certificate files (`.cert`, `.crt`, `.pem`) found in the proxy cert directory. The combined bundle SHALL be written to a temporary file and its path returned for use as `REQUESTS_CA_BUNDLE`.

#### Scenario: Cert directory contains proxy certificates
- **WHEN** `cloud_proxy_cert` is configured (e.g., `cert/uat.cert`) and the parent directory contains certificate files
- **THEN** the system SHALL produce a temp file containing the full certifi CA bundle followed by the contents of each certificate file in the directory

#### Scenario: Cert directory does not exist or is empty
- **WHEN** the cert directory does not exist or contains no certificate files
- **THEN** the system SHALL fall back to the default certifi CA bundle path without creating a combined file

### Requirement: Proxy-scoped context manager
The system SHALL provide a context manager (`proxy_env`) that temporarily sets `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` environment variables for the duration of a `with` block and restores original values on exit.

#### Scenario: Proxy env vars applied and restored
- **WHEN** code executes within the `proxy_env` context manager with a proxy URL and CA bundle path
- **THEN** `os.environ["HTTPS_PROXY"]` SHALL equal the provided proxy URL and `os.environ["REQUESTS_CA_BUNDLE"]` SHALL equal the provided CA bundle path during the block, and both SHALL be restored to their previous values (or removed if previously unset) after the block exits

#### Scenario: Exception during scoped block
- **WHEN** an exception is raised inside the `proxy_env` context manager
- **THEN** the environment variables SHALL still be restored to their original values before the exception propagates

#### Scenario: No proxy configured
- **WHEN** `proxy_url` is `None`
- **THEN** the context manager SHALL not modify any environment variables

### Requirement: Auth flow uses context manager with combined bundle
The `_AzureBearerAuth.auth_flow()` method SHALL use the `proxy_env` context manager with the combined CA bundle path when calling `credential.get_token()`, replacing the current inline env-var manipulation.

#### Scenario: Token retrieval through proxy with combined CA bundle
- **WHEN** Azure proxy is configured and `auth_flow` is invoked
- **THEN** the `get_token()` call SHALL execute with `REQUESTS_CA_BUNDLE` pointing to the combined CA bundle (system CAs + proxy certs) and `HTTPS_PROXY` set to the proxy URL
