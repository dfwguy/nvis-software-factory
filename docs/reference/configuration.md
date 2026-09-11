---
diataxis: reference
nvsf_generated: backend/config_registry.py
---

# Configuration

:::{admonition} Generated page
:class: generated-page

This page is generated from `backend/config_registry.py` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

Every setting is declared once in `backend/config_registry.py`, and three things are derived from that declaration: `factory.toml.example`, this page, and the startup gate's required-setting check. A setting that is missing at boot fails at boot, not at first use.

:::{warning}
A setting marked secret may come from an environment variable or a mounted secret file, and is **refused** if it appears in `factory.toml`. Config files get committed; by the time a warning is noticed the credential is in git history.
:::

## `[assessment]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `workers` | `NVSF_ASSESSMENT_WORKERS` | `int` | `2` | no | Concurrent assessment runs. The binding constraint is the shared LLM endpoint, not local CPU: each run makes roughly a dozen completions, and other teams use the same endpoint. A queued run that starts in two minutes is fine; rate-limiting the endpoint for everyone is not. |

## `[clone]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `depth` | `NVSF_CLONE_DEPTH` | `int` | `1` | no | Shallow clone depth. History is not needed to assess the current state, and fetching it is the slowest part of acquisition. |
| `github_token` | `NVSF_GITHUB_TOKEN` | `str` | _(secret)_ | no | Read-only token for private GitHub repositories. |
| `gitlab_token` | `NVSF_GITLAB_TOKEN` | `str` | _(secret)_ | no | Read-only token for private GitLab repositories. Needs 'read_repository' and nothing else. |
| `max_mb` | `NVSF_CLONE_MAX_MB` | `int` | `512` | no | Refuse a working tree larger than this. Guards the data volume against a repository with large binaries in it. |
| `timeout_sec` | `NVSF_CLONE_TIMEOUT_SEC` | `int` | `300` | no | Hard timeout on a clone. The subprocess is killed, not merely abandoned. |

## `[llm]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `api_key` | `NVSF_LLM_API_KEY` | `str` | _(secret)_ | no | Bearer token for the endpoint. Environment or mounted secret file only. |
| `base_url` | `NVSF_LLM_BASE_URL` | `str` | _(none)_ | yes | OpenAI-compatible endpoint, e.g. an internal NIM deployment. The application refuses to start without it: reasoning is a required pipeline stage and there is deliberately no degraded mode. |
| `evidence_budget_chars` | `NVSF_LLM_EVIDENCE_BUDGET_CHARS` | `int` | `120000` | no | Ceiling on serialized evidence per reasoning pass. Above this the evidence is summarized by map-reduce rather than truncated, so nothing is silently dropped. |
| `max_output_tokens` | `NVSF_LLM_MAX_OUTPUT_TOKENS` | `int` | `8192` | no | Upper bound on a single completion. The remediation pass is the tallest: it returns three buckets of steps, each with a rationale, the files involved and a verification, so a repository with many findings genuinely needs the room. At 4096 it was cut off mid-string and the run failed on unparseable JSON. |
| `max_retries` | `NVSF_LLM_MAX_RETRIES` | `int` | `3` | no | Bounded retries with exponential backoff, on transport errors and 429/5xx only. |
| `model` | `NVSF_LLM_MODEL` | `str` | _(none)_ | yes | Model identifier passed to the endpoint. Recorded with every assessment, so changing it makes previous results reproducible rather than silently stale. |
| `temperature` | `NVSF_LLM_TEMPERATURE` | `float` | `0.2` | no | Low by default: this is analysis, not prose generation. Recorded per call. |
| `timeout_sec` | `NVSF_LLM_TIMEOUT_SEC` | `int` | `180` | no | Per-request timeout. Explicit because a reasoning call with no timeout can hang a worker for minutes (reliability criterion R1). |

## `[logging]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `json` | `NVSF_LOG_JSON` | `bool` | `false` | no | Emit structured JSON lines instead of human-readable text. |
| `level` | `NVSF_LOG_LEVEL` | `str` | `INFO` | no | Root log level. Choices: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `sinks` | `NVSF_LOG_SINKS` | `str` | `stdout` | no | Comma-separated: stdout, file. 'file' writes under the data directory. |

## `[oidc]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `admin_groups` | `NVSF_OIDC_ADMIN_GROUPS` | `str` | `` | no | Comma-separated groups granted the admin role. Empty means nobody is an admin, which is the safe default for a fresh deployment. |
| `client_id` | `NVSF_OIDC_CLIENT_ID` | `str` | _(none)_ | conditional | Client identifier registered with the provider. |
| `client_secret` | `NVSF_OIDC_CLIENT_SECRET` | `str` | _(secret)_ | no | Client secret. Omit for a public client using PKCE alone. |
| `groups_claim` | `NVSF_OIDC_GROUPS_CLAIM` | `str` | `groups` | no | ID token claim holding group membership. |
| `issuer` | `NVSF_OIDC_ISSUER` | `str` | _(none)_ | conditional | Issuer URL. Discovery is fetched from {issuer}/.well-known/openid-configuration. |
| `mock` | `NVSF_OIDC_MOCK` | `bool` | `false` | no | Local development only. Substitutes a fake provider that logs in a fixed user. Refused unless NVSF_ENV=development AND the bind address is loopback. Never set this in a deployment. The startup gate exits non-zero if it is on in production, rather than warning. |
| `role_map` | `NVSF_OIDC_ROLE_MAP` | `str` | `` | no | Comma-separated group=role pairs, e.g. 'nvis-ova=ova,nvis-aic=aic'. Groups with no mapping get the 'viewer' role. |
| `scopes` | `NVSF_OIDC_SCOPES` | `str` | `openid profile email groups` | no | Space-separated scopes. 'groups' is what carries role membership. |
| `session_secret` | `NVSF_SESSION_SECRET` | `str` | _(secret)_ | no | Signing key for the session cookie. Generated and persisted to the data directory on first start if unset, so a restart does not log everyone out. |
| `session_ttl_hours` | `NVSF_SESSION_TTL_HOURS` | `int` | `12` | no | Session lifetime before re-authentication is required. |

## `[retention]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `backup_interval_hours` | `NVSF_BACKUP_INTERVAL_HOURS` | `int` | `24` | no | How often to snapshot the database with VACUUM INTO. 0 disables, which fails durability criterion D3 and is reported as such by the app's own self-check. |
| `backup_retain_days` | `NVSF_BACKUP_RETAIN_DAYS` | `int` | `14` | no | How long snapshots are kept. |
| `workspace_retain_hours` | `NVSF_WORKSPACE_RETAIN_HOURS` | `int` | `6` | no | How long a clone is kept after its assessment finishes. Cloned source is not durable state; it is kept briefly so a failed run can be retried without re-fetching. |

## `[runtime]`

| Setting | Environment variable | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `bind_addr` | `NVSF_BIND_ADDR` | `str` | `127.0.0.1` | no | Address gunicorn binds. Defaults to loopback so a fresh deployment is not exposed before TLS and OIDC are configured. |
| `data_dir` | `NVSF_DATA_DIR` | `path` | `var` | no | Root of all durable state. Must be a bind mount in production: a named volume can be removed by 'docker volume prune'. |
| `env` | `NVSF_ENV` | `str` | `production` | no | Deployment mode. 'development' unlocks the mock identity provider and relaxes the TLS requirement; it is refused on a non-loopback bind. Choices: `production`, `development`. |
| `port` | `NVSF_PORT` | `int` | `8000` | no | Port gunicorn binds inside the container. |
| `public_url` | `NVSF_PUBLIC_URL` | `str` | _(none)_ | yes | Externally reachable base URL, e.g. https://factory.nvidia.com. Used to build the OIDC redirect URI, so it must match what is registered with the provider. No trailing slash. |
| `tls_cert` | `NVSF_TLS_CERT` | `path` | _(none)_ | no | PEM certificate. Required in production; the app refuses to serve OIDC session cookies over plaintext. |
| `tls_key` | `NVSF_TLS_KEY` | `path` | _(none)_ | no | PEM private key matching tls_cert. |
| `web_threads` | `NVSF_WEB_THREADS` | `int` | `4` | no | Threads per worker. Enough that a slow contract-bundle response cannot make the health check time out. |
| `web_timeout_sec` | `NVSF_WEB_TIMEOUT_SEC` | `int` | `300` | no | Gunicorn worker timeout. Long because the mapping assistant makes a reasoning call inside a request; finite because an unbounded timeout turns one hung upstream call into a worker that never returns. |
| `web_workers` | `NVSF_WEB_WORKERS` | `int` | `2` | no | Gunicorn worker processes. Deliberately not '2 * cpu + 1': each worker runs its own assessment pool and its own SQLite connections, so the count multiplies both load on the shared reasoning endpoint and write contention on one database file. Capped at the CPU count at startup. |
