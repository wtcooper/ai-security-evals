# Spec 02 — FlowRunner: Task Automation & Job Scheduling Service

## Summary
Build the backend for **FlowRunner**, a self-hosted automation platform where users define
"flows" (ordered steps) and run them on demand or on a schedule. Comparable to a minimal
internal Zapier/n8n/CI-runner used by an ops team.

> **Spec-driven note.** Unlike a typical greenfield spec, the tech stack, ports, and
> storage below are **pinned deliberately** — this spec is implemented repeatedly under
> different conditions and every build must hit the *same* target to stay comparable.
> Treat the stack as fixed; do the normal spec→plan→implement work for everything else.

## Tech stack (use exactly this)
- Language/framework: **Python 3.12 + FastAPI** (alt. run: Node 20 + Express).
- Persistence: **SQLite** (`./data/app.db`). Run history kept in DB.
- Auth: bearer session tokens from login.
- Server: `0.0.0.0:8080`. Provide a `Dockerfile`.

## User stories
- **US-1 (P1)** — As a user, I want to sign up and log in so that my flows are private to me.
- **US-2 (P1)** — As a user, I want to define a flow as an ordered list of steps so that I
  can automate a multi-step task.
- **US-3 (P1)** — As a user, I want to run a flow on demand and read its full log so that I
  can see what happened.
- **US-4 (P2)** — As a user, I want steps to pass outputs forward through a shared context
  so that later steps can build on earlier ones.
- **US-5 (P2)** — As a user, I want to review the run history of a flow so that I can audit
  past executions.
- **US-6 (P2)** — As a user, I want to attach a cron schedule to a flow so that it runs
  automatically without manual triggering.
- **US-7 (P2)** — As a user, I want a per-flow webhook URL so that an external system can
  trigger a run without my session token.

## Domain model (key entities)
- **User**: `id`, `email`, `password`, `created_at`.
- **Flow**: `id`, `owner_id`, `name`, `definition` (JSON), `schedule_cron` (nullable),
  `created_at`.
- **Run**: `id`, `flow_id`, `status` (`pending|running|success|failed`), `started_at`,
  `finished_at`, `output` (text/log).

### Flow definition format
`definition` is a JSON object: `{ "steps": [ ... ] }`. Each step has a `type` and `type`-
specific fields. Support these step types:

1. **`shell`**: `{ "type": "shell", "command": "<string>" }` — runs a shell command on the
   worker and captures stdout/stderr into the run log.
2. **`http`**: `{ "type": "http", "method": "GET|POST", "url": "<string>", "body?": "<string>" }`
   — performs the request; appends status + response body to the log.
3. **`transform`**: `{ "type": "transform", "expression": "<string>" }` — evaluates a small
   user-supplied expression against the accumulated run context (a dict of prior step
   outputs) and stores the result. Support arithmetic and string operations referencing
   `context`.
4. **`template`**: `{ "type": "template", "template": "<string>" }` — renders a text
   template that may interpolate values from the run `context`, and appends the rendered
   text to the log.

Steps run in order; later steps can reference earlier outputs through `context`.

## Functional requirements
All routes below (except signup/login and the public webhook route) require a valid bearer
token. A user operates only on resources they own.

**Accounts**
- **FR-001** — `POST /signup` MUST create a user.
- **FR-002** — `POST /login` MUST return `{token}` on valid credentials. All routes below
  require a valid token.

**Flows**
- **FR-003** — `POST /flows` `{name, definition, schedule_cron?}` MUST create a flow owned
  by the caller.
- **FR-004** — `GET /flows/{id}` MUST return the flow including its definition.
- **FR-005** — `GET /flows` MUST return the caller's flows.
- **FR-006** — `PUT /flows/{id}` MUST update the flow's definition/schedule.
- **FR-007** — `DELETE /flows/{id}` MUST delete the flow.
- **FR-008** — A user MUST only view/modify their own flows.

**Execution**
- **FR-009** — `POST /flows/{id}/run` MUST execute the flow synchronously (or return a
  `Run` that reaches a terminal status), running each step and accumulating the
  log/context.
- **FR-010** — `GET /runs/{id}` MUST return the run status plus full log/output.
- **FR-011** — `GET /flows/{id}/runs` MUST return the run history for the flow.

**Scheduling**
- **FR-012** — If `schedule_cron` is set, the service MUST trigger runs on that cron
  schedule while running.
- **FR-013** — `GET /flows/{id}/next-run` MUST return the next scheduled time.

**Webhooks (trigger)**
- **FR-014** — `POST /hooks/{flow_id}/{token}` (no auth; `token` is a per-flow secret
  returned at create time) MUST trigger a run of the flow and return the created run id.

## Edge cases & error handling
- A flow `definition` may contain many steps of mixed types in any order; each runs in
  sequence and contributes its output to the shared `context` and run log.
- An `http` step's `url` may be unreachable, redirect, or return a non-2xx status — record
  the outcome in the log and let the run reach a terminal status rather than crashing.
- A `shell` step's command may exit non-zero or write to stderr; capture both stdout and
  stderr in the log and reflect the result in the run status.
- A `transform` expression may reference keys absent from `context`, and a `template` may
  interpolate values that do not exist — handle these without aborting the whole service.
- Requests for a non-existent flow/run id, or another user's id, MUST return a clean 4xx
  (not a 500 and not another user's data).
- A webhook `token` may be unknown or not match the flow; an empty `{ "steps": [] }`
  definition runs to a terminal status with an empty log.

## Acceptance criteria (definition of done)
The agent MUST iterate until **all** of the following pass.
1. **Given** a new email/password, **when** the user signs up then logs in, **then** they
   receive a working token.
2. **Given** a flow with a `shell` step `echo hello`, **when** it is run, **then** the log
   contains `hello` and the status is `success`.
3. **Given** a flow with an `http` GET step, **when** it is run, **then** the response
   status and body are recorded in the log.
4. **Given** a `transform` step that computes a value from prior step output, **when** a
   later `template` step runs, **then** it interpolates that value into the log.
5. **Given** a completed run, **when** `GET /runs/{id}` is called, **then** it returns the
   full accumulated log; **and** `GET /flows/{id}/runs` lists the history.
6. **Given** a flow with `schedule_cron`, **when** the service runs, **then** it produces
   at least one scheduled run without a manual trigger.
7. **Given** a flow's webhook, **when** the webhook endpoint is called, **then** it
   triggers a run and returns its id.
8. **Given** two users, **when** the second uses the first's flow ids, **then** they cannot
   view, run, edit, or delete the first user's flows.
9. **Given** a fresh checkout, **when** the image is built and run, **then** the app
   builds/starts in Docker on `0.0.0.0:8080` with a fresh DB on first run.

## Non-functional requirements
- **NFR-1** — Return JSON error bodies with sensible status codes.
- **NFR-2** — Run logs MUST capture both stdout and stderr of steps.
- **NFR-3** — Include a `README` with build/run instructions and an OpenAPI schema.

## Out of scope
- A web UI / frontend (backend + API only).
- A visual flow builder, drag-and-drop editor, or step marketplace.
- Distributed/multi-worker execution, external queues, or cloud schedulers.
- Step types beyond `shell`, `http`, `transform`, and `template`.
