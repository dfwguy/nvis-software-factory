---
diataxis: reference
nvsf_generated: standards/pillars/data-security.md
---

# Data security

:::{admonition} Generated page
:class: generated-page

This page is generated from `standards/pillars/data-security.md` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

**Severity ceiling:** `blocker` — no finding against this pillar can exceed it, however strongly the model argues.

| Criterion | Statement | Deterministic detector |
|---|---|---|
| `S1` | No credentials in the repository, including its history | yes |
| `S2` | Mutating endpoints require authentication | partial |
| `S3` | Authorization is default-deny | partial |
| `S4` | Credentials are not logged | yes |
| `S5` | Transport is encrypted where it crosses a host boundary | partial |
| `S6` | Dependencies are pinned and scanned | yes |
| `S7` | Input that reaches a shell or a query is not concatenated | yes |

---

**The question:** who can read this data, and who can change it?

Most of what goes wrong here is not sophisticated. It is a token pasted into a config file that got
committed, or an internal API that assumed the corporate network was a boundary.

## Criteria

### S1 — No credentials in the repository, including its history

*Detector: yes.*

- **Pass:** credentials come from the environment, a mounted secret file, or a secret manager. The
  repository contains only placeholders.
- **Fail:** any private key, API token, password, or connection string with embedded credentials
  appears in a tracked file.

`.gitignore` is not a control — it prevents an accidental add and does nothing about `git add -f`,
about a file tracked before the rule existed, or about history. A credential that ever reached a
commit is compromised and must be rotated, not merely deleted.

### S2 — Mutating endpoints require authentication

*Detector: partial.*

- **Pass:** every endpoint that changes state or returns non-public data requires an authenticated
  principal, and the check is centralized rather than repeated per route.
- **Fail:** an unauthenticated `POST`, `PUT`, `PATCH` or `DELETE`, or an unauthenticated read of
  cluster data.

"It is only on the internal network" is not authentication. It is an assumption about a boundary
that has been wrong before.

### S3 — Authorization is default-deny

*Detector: partial.*

- **Pass:** a route with no policy attached is denied. Adding an endpoint without thinking about
  access control fails closed and fails loudly.
- **Fail:** an allow-by-default model where forgetting a decorator silently exposes an endpoint.

### S4 — Credentials are not logged

*Detector: yes.*

- **Pass:** a redaction filter in the logging configuration, applied centrally.
- **Fail:** request bodies, headers, environment dumps or exception context written to logs without
  filtering. `Authorization` headers in a debug log are a real and common finding.

### S5 — Transport is encrypted where it crosses a host boundary

*Detector: partial.*

- **Pass:** TLS for anything leaving the host. Certificate verification is on.
- **Fail:** plaintext HTTP between hosts, or `verify=False` / `InsecureSkipVerify` /
  `rejectUnauthorized: false`. Disabling verification against a self-signed certificate is
  understandable and still wrong; pin the certificate instead.

### S6 — Dependencies are pinned and scanned

*Detector: yes.*

- **Pass:** a lockfile or pinned version ranges, and something that checks them against a
  vulnerability database.
- **Fail:** unpinned dependencies, which make a build unreproducible and mean the vulnerability
  status of what shipped is unknown.

### S7 — Input that reaches a shell or a query is not concatenated

*Detector: yes.*

- **Pass:** parameterized queries; subprocess invocation with an argument list.
- **Fail:** f-strings into SQL, or `shell=True` with interpolated input.

This matters more than usual in our tooling, because the interpolated value is often a hostname or
node list that came from a file someone else generated.

## Remediation patterns

**Committed secret.** Rotate first — it is in the history and in every clone. Then untrack the file,
add it to `.gitignore`, and add a path-based CI check so the class cannot recur. Rewriting history
is optional; rotating is not.

**Ad-hoc auth checks per route.** Move to a single `before_request` gate that authenticates once and
authorizes against a per-route declaration. The win is that the default for a new route becomes
"denied" instead of "whatever the author remembered".

**`verify=False` against a self-signed cert.** Ship the CA certificate with the client and point
`verify` at it. The connection still works offline and an interception is still detected.
