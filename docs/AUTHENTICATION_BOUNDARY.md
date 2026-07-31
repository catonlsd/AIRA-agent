# AIRA-X authentication boundary

This document records the Phase 3D authentication-gate separation. It describes
application behavior only; Cloudflare, Oracle, Vercel and DNS are not configured
by this change.

## Authentication classes

- **Public operational** — no user or service credential: `/`, `/health`,
  `/ready`, `/docs`, `/redoc`, `/openapi.json`, `/auth/register`,
  `/auth/login`.
- **Authenticated user** — a valid account bearer token is required outside the
  explicit local-development bypass.
- **Privileged service/operator** — `/operator/*` requires the server-side
  service credential. A user bearer does not grant operator access.
- **Internal callback** — none of the currently registered HTTP routers exposes
  an internal callback endpoint.

The service credential is not a user credential. It must never be placed in
`NEXT_PUBLIC_*`, browser storage, browser source, query parameters or browser
request headers.

## Endpoint authentication matrix

| Endpoint group | Current gate after Phase 3D | Intended class | Accepted principal | Ownership authorization deferred to PR 2 |
|---|---|---|---|---|
| `/`, `/health`, `/ready` | Public-path allowlist | Public operational | Anonymous | No |
| `/docs`, `/redoc`, `/openapi.json` | Public-path allowlist | Public operational | Anonymous | No; disable API docs at ingress if required |
| `POST /auth/register`, `POST /auth/login` | Public; login has failure limiting | Public authentication bootstrap | Anonymous | Account lifecycle hardening remains |
| `GET /auth/me`, `POST /auth/logout` | User gate plus route validation | Authenticated user | Account bearer | Durable session revocation belongs to BFF PR |
| `/workspaces/*` | User gate plus account/role checks | Authenticated user | Account bearer | Existing membership authorization retained |
| `/resources/*`, `/runs/*`, `/search*`, `/pins*` | User gate | Authenticated user | Account bearer | Per-resource review remains in PR 2 |
| `/context*`, `/bundles*`, `/jobs*`, `/activity/*` | User gate | Authenticated user | Account bearer | Per-resource review remains in PR 2 |
| `/assistant/*`, `/chat` | User gate | Authenticated user | Account bearer | Conversation/history scoping review remains |
| `/aira-x/run`, `/aira-x/stream` | User gate | Authenticated user | Account bearer | Workflow owner persistence remains in PR 2 |
| `/aira-x/approve`, `/aira-x/reject` | User gate | Authenticated user | Account bearer | Run ownership check is a known PR 2 P1 |
| `/aira-x/runs*`, `/aira-x/traces` | User gate | Authenticated user | Account bearer | Run listing/read/delete scoping is a known PR 2 P1 |
| `/aira-x/tools*`, `/aira-x/agents*`, `/aira-x/overview` | User gate | Authenticated user metadata | Account bearer | No owner data should be added |
| `/upload` | User gate; route resolves account/workspace scope | Authenticated user | Account bearer | Existing upload ownership retained |
| `/documents`, `/documents/{id}`, `/summarize` | User gate | Authenticated user | Account bearer | Document list/delete/summarize IDOR is a known PR 2 P1 |
| `/history` | User gate | Authenticated user | Account bearer | History ownership is deferred to PR 2 |
| `/artifacts/{owner}/{filename}` | User gate plus existing capability/account checks | Authenticated user | Account bearer | Full legacy-owner review remains |
| `/preferences/*` | User gate plus scope resolution | Authenticated user | Account bearer | Existing scope behavior retained |
| `/operator/*` | Explicit route-level service check | Privileged service/operator | Service key only | Operator data is intentionally not user-owned |
| Unregistered webhook/callback modules | No exposed route | Internal callback / unresolved | None | Define authentication before registering any callback |

Authentication and authorization are deliberately separate. Phase 3D proves who
the caller is and prevents a service key from becoming a user. It does not claim
that every resource endpoint has completed owner-level authorization.

## Environment behavior

`USER_AUTH_ENABLED=true` is required in preview and production.

Anonymous protected-resource compatibility exists only when all of the following
are true:

```text
ENVIRONMENT=development
ALLOW_ANONYMOUS_PROTECTED_ACCESS=true
DEVELOPMENT_AUTH_BYPASS=true
```

The bypass is disabled by default. Preview and production fail startup if either
anonymous/bypass switch is enabled, user authentication is disabled, required
authentication secrets are missing or placeholder-strength, or a privileged
credential is configured through a known `NEXT_PUBLIC_*` name.

## Login protection

Failed logins use a bounded, process-local client-address window. Responses do
not distinguish an unknown account from a wrong password. The limiter is
deterministically resettable for tests.

This limiter is not sufficient for multi-instance external beta. The BFF/session
phase must use a shared abuse-control store and stable authenticated identity.

## Transitional limitations

- The account bearer remains in browser `localStorage` for the gated internal
  preview. This is unresolved P1 debt and is not suitable for external beta.
- The browser operator console is disabled. Privileged credentials are
  server-to-server only.
- The internal preview assumes named trusted testers behind an MFA-backed
  identity-aware gateway. Infrastructure configuration is separately authorized.
- Document/workflow/approval ownership enforcement is the next dedicated PR.
- External beta requires an OIDC-capable Vercel BFF with durable server-managed
  sessions and secure HttpOnly cookies.
