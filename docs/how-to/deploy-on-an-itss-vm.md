---
diataxis: how-to
description: Stand up the Software Factory on an ITSS VM with Docker Compose, OIDC and a bind-mounted data directory.
---

# How to deploy on an ITSS VM

Gets you from a fresh ITSS VM to a working deployment behind OIDC. Twenty minutes of work plus
however long the ITSS ticket for the OIDC client registration takes.

## Before you start

- An ITSS VM you have `sudo` on, with Docker and the Compose plugin installed.
- A DNS name pointing at it, and a TLS certificate for that name.
- An OIDC client registered with the internal provider (see step 3 — do this first, it has a
  lead time).
- Network egress to your GitLab/GitHub instances and to the reasoning endpoint.

:::{important}
The reasoning endpoint is not optional. If the VM cannot reach an OpenAI-compatible endpoint, the
application will not start — by design, because a Factory that silently degrades to
scanner-only output produces reports that look complete and are not. Confirm reachability from the
VM before you go further.
:::

## 1. Pick a data directory and make it a bind mount

```bash
sudo mkdir -p /srv/nvsf/data
sudo chown 10001:10001 /srv/nvsf/data
```

`10001` is the non-root UID the container runs as.

A **bind mount**, not a named volume. `docker volume prune` removes unused named volumes without
asking what is in them, and "unused" includes "the container is currently recreating". A path on
the host filesystem is visible to `ls`, backed up by whatever backs up the VM, and survives every
Docker operation. This is the durability pillar's criterion D1, applied to the tool that enforces
it.

## 2. Get the code and the configuration

```bash
git clone https://gitlab-master.nvidia.com/nvis-ova/nvis-software-factory.git /opt/nvsf
cd /opt/nvsf
cp .env.example .env
```

## 3. Register the OIDC client

Ask ITSS for a client registration with:

- **Redirect URI**: `https://factory.your-site.nvidia.com/api/auth/callback` — exactly, including
  scheme and host. It is derived from `NVSF_PUBLIC_URL`, and a mismatch is the single most common
  cause of a login loop.
- **Grant type**: authorization code with PKCE.
- **Scopes**: `openid profile email groups`. The `groups` scope is what carries role membership;
  without it every user lands as a viewer.

## 4. Fill in `.env`

The settings that must be right. Everything else has a working default —
{doc}`../reference/configuration` is the full list.

```bash
NVSF_PUBLIC_URL=https://factory.your-site.nvidia.com
NVSF_BIND_ADDR=0.0.0.0
NVSF_DATA_DIR=/data

NVSF_TLS_CERT=/etc/nvsf/tls/fullchain.pem
NVSF_TLS_KEY=/etc/nvsf/tls/privkey.pem

NVSF_OIDC_ISSUER=https://<provider>/
NVSF_OIDC_CLIENT_ID=<from step 3>
NVSF_OIDC_CLIENT_SECRET=<from step 3>
NVSF_OIDC_ROLE_MAP=nvis-ova=ova,nvis-aic=aic,nvis-ethernet=ethernet,nvis-ib=ib
NVSF_OIDC_ADMIN_GROUPS=nvis-ova-admins

NVSF_LLM_BASE_URL=https://<nim-endpoint>/v1
NVSF_LLM_MODEL=<model id>
NVSF_LLM_API_KEY=<key>
```

Three of these are worth a second look:

`NVSF_BIND_ADDR`
: Defaults to `127.0.0.1` so that a half-finished deployment is not reachable before TLS and OIDC
  are configured. Change it only once the two settings above it are real.

`NVSF_OIDC_ADMIN_GROUPS`
: Empty by default, meaning nobody is an admin. That is deliberate for a fresh deployment — grant
  it to a group you control, not to a broad one.

`NVSF_OIDC_MOCK`
: Leave it alone. It substitutes a fake identity provider, and the startup gate refuses to boot if
  it is set outside development on a loopback bind. It exists for local work only.

:::{warning}
Secrets go in `.env` or a mounted secret file, never in `factory.toml`. The config loader
**refuses** a secret that appears in the TOML file rather than warning about it, because a config
file gets committed and by the time anyone notices the credential is in git history.
:::

## 5. Start it

```bash
docker compose up -d
docker compose logs -f
```

Read the startup log. The gate validates configuration, LLM reachability, data-directory
writability and OIDC discovery *before* serving, and reports every problem it finds in one pass
rather than failing on the first. If it exits, the log says exactly which settings are wrong.

## 6. Verify

```bash
./bin/verify-deploy.sh https://factory.your-site.nvidia.com
```

Run it **from the VM**: the storage checks need Docker access, and those are the ones that catch
the failure this project exists because of.

It runs anonymously, and that is the point — the most serious thing it can find is an endpoint
that answers without a session. It also checks TLS, security headers, that the data directory is
genuinely a bind mount rather than a named volume, and that the container is not running as root.

The per-dependency checks are behind the session, so they are skipped unless you supply a cookie.
Sign in, copy `nvsf_session` from your browser's devtools, and run it again:

```bash
NVSF_SESSION_COOKIE='nvsf_session=...' \
  ./bin/verify-deploy.sh https://factory.your-site.nvidia.com
```

That adds the store, migration, snapshot and reasoning-endpoint checks.

Then open **Platform health** in the UI. You want the LLM probe reachable and your roles listed.
Empty roles after a successful login means the `groups` claim is not arriving — check the scope
from step 3 and `NVSF_OIDC_GROUPS_CLAIM`.

## 7. Confirm the backups are real

Snapshots default to every 24 hours with 14 days of retention, written under the data directory.
After the first interval:

```bash
ls -la /srv/nvsf/data/backups/
```

Those snapshots are on the same volume as the live database, which protects you from corruption
and from an accidental delete, and not at all from losing the volume. Get the VM's backup covering
`/srv/nvsf/data`, and then restore one snapshot into a scratch copy to prove the path works. An
unverified backup is a belief, not a control — which is the Factory's own criterion D3, and it
applies here too.

## Upgrading

```bash
cd /opt/nvsf && git pull
docker compose up -d --build
```

Migrations are numbered and applied at startup, so there is no separate migration step. Take a
snapshot first anyway:

```bash
sqlite3 /srv/nvsf/data/store/factory.db \
  "VACUUM INTO '/srv/nvsf/data/backups/pre-upgrade.db'"
```

## When something is wrong

**It exits immediately.** Read the log — the gate lists every failed check. Missing
`NVSF_LLM_BASE_URL` and an unwritable data directory look identical from outside and are named
individually in that output.

**Login loops back to sign-in.** The redirect URI registered with the provider does not match
`NVSF_PUBLIC_URL` + `/api/auth/callback`. Compare them character by character, including the
scheme.

**Signed in but everything is forbidden.** The `groups` claim is not arriving or your group is not
in `NVSF_OIDC_ROLE_MAP`. **Platform health** shows the roles the session actually has.

**Assessments fail during reasoning.** Probe the endpoint from inside the container — an
egress rule that permits the VM but not the container bridge is the usual cause.

## Related

- {doc}`../reference/configuration` — every setting.
- {doc}`../explanation/the-reboot-that-lost-the-data` — why the bind mount is not a preference.
