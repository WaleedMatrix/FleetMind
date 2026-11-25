# FleetMind security architecture

Milestone 11A uses a single organization. Registered assets, predictions,
model reports, and approved monitoring views are shared according to role.
Copilot conversations and messages have individual owners.

## Trust boundaries and threat model

| Boundary or risk | Control |
| --- | --- |
| Browser to Next.js and FastAPI | The browser uses a fixed same-origin proxy. FastAPI verifies the session and authorizes every API request. Only minimal health and login are public. |
| URL and object identifiers | The proxy has a method and path allowlist. Copilot queries bind the conversation ID to the verified owner. Ordinary users cannot access ownerless legacy conversations. |
| Session theft and fixation | Sessions use random opaque tokens in HttpOnly cookies. PostgreSQL stores SHA-256 token digests. Login and password change issue new tokens. Logout, deactivation, and role changes revoke sessions. HTTPS is required outside explicit loopback development. |
| CSRF and XSS | Cookie-authenticated writes require a configured origin and a session-bound CSRF value. Login checks the origin before credentials are verified. Templates render untrusted content as text. Security headers constrain framing, resource origins, and referrers. |
| Brute-force login | Generic failures, an Argon2id dummy verification for unknown accounts, bounded login concurrency, and per-account and per-peer attempt limits. |
| Copilot cost, abuse, and prompt injection | Per-principal throttles and stream limits supplement the existing provider deadlines, typed read-only tools, and evidence validation. Conversation context, stored text, and retrieved passages remain untrusted. |
| Unauthorized or revoked SSE subscriptions | HTTP authorization precedes streaming. Long-lived responses periodically recheck the originating session against PostgreSQL. Copilot streams reserve and save data only within the verified owner scope. |
| Credential exposure | Cookies, bearer tokens, passwords, provider keys, and raw conversation bodies are excluded from audit events. The frontend proxy forwards a small allowlist and keeps user-controlled upstream URLs out of request construction. |
| Worker, broker, and database access | The telemetry worker communicates directly with the private broker and database. HTTP simulators use revocable prediction-only bearer credentials. Development listener ports stay on loopback. Database and broker identities are trusted infrastructure. |
| Privilege escalation | Central role decisions protect administrative routes. User updates serialize the final-active-administrator check. Backend verification, not UI visibility, is the enforcement boundary. |

Users and ingress are trusted to provide a correct HTTPS deployment origin.
Database and container administrators can bypass application permissions.
Production needs separate service accounts, protected backups, explicit
origin configuration, TLS termination, and ingress limits. A browser script
executing on the FleetMind origin can act with the user's current permissions.
This design limits that risk but cannot make an authenticated XSS harmless.
Automated verification covers application behavior and does not replace an
independent security assessment.

## Authentication and session lifecycle

1. The browser submits credentials to the Next.js bridge, which forwards them
   to the configured FastAPI upstream over the private network. FastAPI verifies
   the origin and checks the password with Argon2id. A successful login issues
   a new random 256-bit token and revokes a previous session for the same
   account when that cookie accompanies the login.
2. PostgreSQL stores the SHA-256 digest of each token. The browser sends the
   token in an HttpOnly, SameSite=Lax cookie scoped to the current host and
   path `/`. Production uses Secure cookies and the `__Host-` prefix. A second
   cookie contains a session-bound CSRF value, which browser code copies to
   `X-FleetMind-CSRF` for writes. FastAPI verifies the value and exact Origin.
3. Middleware resolves the user and current role from the active session on
   each API request. The session has an absolute expiry. An account can have
   up to eight active sessions. Password changes revoke all earlier sessions
   and issue a replacement. Activation and role changes revoke existing
   sessions. Users can revoke their own sessions or sign out.
4. SSE authorization runs before the connection opens. The stream checks
   absolute expiry and revalidates persisted session and role approximately
   every three seconds. A revoked or unverified stream emits `session_expired`
   and closes. Copilot cancels unfinished work and checks authorization again
   before saving its final response. Requests already completing can race
   with revocation.
5. FastAPI returns 401 for missing or expired sessions and 403 for a rejected
   role, origin, or CSRF check. Foreign and ownerless Copilot conversation
   identifiers produce the same 404 as a missing conversation.

The public `GET /health` probe returns only liveness. `POST /api/v1/auth/login`
is the pre-authentication credential exchange. The API exposes no public
interactive docs. Browser data requests use a same-origin Next.js bridge.
Cross-origin clients receive no CORS permissions. The bridge forwards selected
cookies, origin, CSRF, and telemetry cursor headers, refuses upstream redirects,
and streams SSE with cancellation and bounded timeouts. Page gating verifies
a session with FastAPI before serving a protected route. API authorization is
independent of page gating.

## Permission matrix

| Operation | Viewer | Engineer | Administrator |
| --- | --- | --- | --- |
| Dashboard, assets, history, model reports, SHAP | Yes | Yes | Yes |
| Telemetry status, recent assessments, metrics, live stream | Yes | Yes | Yes |
| Register or edit assets and submit assessments | — | Yes | Yes |
| Knowledge search and telemetry dead-letter diagnostics | — | Yes | Yes |
| Copilot tools and owned conversations | — | Own | Own |
| Own password and sessions | Yes | Yes | Yes |
| User and role management, audit review | — | — | Yes |
| Explicit legacy conversation adoption or archival | — | — | Yes |
| List and revoke simulator credentials | — | — | Yes |

Copilot read-only tools see shared engineering data. A validated citation in a
private response is visible only with that response. Underlying shared
asset, prediction, and knowledge records retain their independent role checks.
Represented role and user identifiers supplied in request bodies carry no
authorization authority.

## Deploying the migration and creating accounts

Back up and confirm the intended target in `DATABASE_URL`. Install
`requirements.txt` and run `python -m alembic upgrade head` from the repository
root. Verify `python -m alembic current` reports `0007_application_security`.
The migration adds four tables and a nullable owner column and index. It leaves
existing asset, prediction, knowledge, telemetry, and conversation data in place.
The forward-only migration was tested with legacy rows on disposable PostgreSQL.

Run `python -m scripts.manage_security bootstrap --username your-admin` from an
interactive terminal. Enter and confirm a password of 12 to 128 characters.
Bootstrapping requires an empty user registry. Create engineering and viewer
accounts from Administration, share their initial passwords via a separate
trusted channel, and have each user change their password in Account and sessions.
Use the displayed user ID when assigning a legacy conversation to an active
engineer or administrator. Legacy records can also be archived with their
owner field empty. Archival preserves their messages.

## Environment and deployment

| Setting | Behavior |
| --- | --- |
| `FLEETMIND_AUTH_ORIGINS` | Comma-separated exact frontend origins, including any nondefault port. Supply HTTPS origins for production. |
| `FLEETMIND_AUTH_INSECURE_LOCAL_HTTP` | Defaults to 0. Set 1 explicitly for loopback HTTP, such as http://127.0.0.1:3000. |
| `FLEETMIND_AUTH_SESSION_MINUTES` | Absolute session lifetime. Default 480, accepted range 5–1440. |
| `FLEETMIND_API_URL` | Server-side Next.js upstream origin. Default http://127.0.0.1:8000. |
| `FLEETMIND_PREDICTION_TOKEN_FILE` | Preferred local file configuration for the HTTP sensor simulator. |
| `FLEETMIND_PREDICTION_TOKEN` | Optional process-only credential for the same simulator. |
| `DATABASE_URL` | Server, worker, and operator configuration. Keep it in a secret store or restricted environment. |

Use HTTPS and HSTS at the browser-facing ingress, including for Next.js.
Keep FastAPI behind a trusted frontend gateway or private network. Expose only
the browser-facing service to users. Validate the public host at ingress and
strip client-supplied forwarding headers. Honor SSE streaming, disable cache and
response buffering on API paths, and configure ingress header, request-body,
connection, and rate limits. Use separate least-privilege infrastructure
identities for runtime and Alembic where practical. Keep database and broker
listeners private and authenticate and encrypt their production links. Treat
local Redpanda as a development profile. Secure backups, restrict secrets,
and use only vetted embedding checkpoints and a trusted provider.

## Simulator service credentials

Run the provisioning CLI from an authorized operator account with database
access. Point --output at a new file in a directory with a private OS ACL,
especially on Windows. The CLI prints the credential identifier and writes
the token only to that file.

    python -m scripts.manage_security create-service --name lab-simulator --administrator your-admin --output "C:\private\simulator.token" --days 30
    $env:`FLEETMIND_PREDICTION_TOKEN_FILE` = 'C:\private\simulator.token'
    python -m scripts.simulate_sensors --count 20 --scenario normal

The token is a revocable bearer credential scoped to direct
`POST /api/v1/predict` with `source: simulated`. It has a 30-day default lifetime
and a 90-day maximum. Revoke it under Administration → Service credentials.
The broker simulator and inference worker continue using their existing private
infrastructure connections and require no application user session.

## Abuse controls and audit

| Limit | Default and scope |
| --- | --- |
| Login attempts | 5 per normalized username and 40 per direct peer per rolling minute, per API process. |
| Argon2id work | 19 MiB, two iterations, one lane, with four simultaneous password operations per process. |
| Copilot chat and streamed messages | 12 per principal per minute, one concurrent request per principal, eight per API process. |
| Knowledge searches and SHAP explanations | 30 each per principal per minute. |
| Prediction submission | 60 per user or simulator credential per minute. |
| Telemetry SSE | Three connections per principal and 32 per API process. Maximum upstream stream lifetime is five minutes. |
| Request bodies | 4 KiB for login and password changes, 8 KiB for prediction, knowledge search, and Copilot chat/stream, 64 KiB for general writes. |

Requests above the applicable rate or concurrency cap return 429 with
`Retry-After`. Oversize bodies return 413. Limits are process-local. Next.js
proxy requests normally share a direct peer, so apply separate per-client
limits at the ingress before scaling. Existing Copilot orchestration
deadlines, tool validation, and call limits still apply.

Audit events include successful and failed sign-ins, logout, revocation,
password changes, role and activation changes, conversation adoption or
archival, and credential provisioning. Significant denials are sampled per
peer. Entries use action names, UUIDs, and timestamps. Passwords, tokens,
provider keys, request bodies, and conversation contents are omitted. Ingress
and Uvicorn access logs should redact query strings that contain conversation
search terms. Production operators are responsible for audit retention, export,
monitoring, and alerting.
There is no distributed rate limiter, MFA, identity federation, self-service
password recovery, or tenant separation. The Next.js CSP allows inline
hydration scripts and styles. Same-origin script execution would have the
user's active permissions.

## Dependency review

On 2026-11-25, npm audit reported zero advisories for the frontend lockfile.
PyPI pip-audit reported 19 entries across the installed Python environment.
The report includes duplicate advisory entries with different aliases.
No finding was reported for the newly declared argon2-cffi 25.1.0.

| Package | Installed | Findings |
| --- | --- | --- |
| sentence-transformers | 5.2.0 | PYSEC-2026-4164. Advisory lists 5.6.0 as fixed. |
| transformers | 4.57.6 | Multiple advisories, including PYSEC-2026-2289, PYSEC-2026-3929, and PYSEC-2026-4174. |
| setuptools | 65.5.0 | Multiple advisories, including PYSEC-2025-49 and GHSA-xmj3-9gf7-h52w. |

The findings remain open in this environment. Validate dependency upgrades
against the frozen model and existing embedding index prior to production
deployment. Advisory review covers published package findings and is scoped
to the audited environment and lockfile.

## Validation

Set `FLEETMIND_MIGRATION_TEST_DATABASE_URL` and
`FLEETMIND_TELEMETRY_TEST_DATABASE_URL` to disposable PostgreSQL and point
`FLEETMIND_TELEMETRY_TEST_BOOTSTRAP` at a disposable broker. Run
`python -m alembic check` after migrating the disposable database, then run
`python -m pytest` and `ruff check .`. Run `npm run test:proxy`,
`npm run lint`, `npm run build`, and `npx tsc --noEmit` from `frontend`.

The local run passed 86 Python tests, four proxy tests, and all 51 scripted
Copilot cases. Migration tests preserved legacy table identities and data.
Edge smoke tests covered administrator, engineer, and viewer flows at desktop
and 320 px, including password rotation, telemetry session revocation, and
role-specific access. Both frozen XGBoost artifact SHA-256 digests matched.
