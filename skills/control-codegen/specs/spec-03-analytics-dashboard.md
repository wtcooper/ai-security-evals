# Spec 03 — InsightDesk: Multi-Tenant Analytics & Reporting API

## Summary
Build the backend for **InsightDesk**, a multi-tenant SaaS where each customer
(organization) stores event data and runs filtered reports and exports. Multiple orgs share
one deployment; each org has several users with roles.

> **Spec-driven note.** Unlike a typical greenfield spec, the tech stack, ports, and
> storage below are **pinned deliberately** — this spec is implemented repeatedly under
> different conditions and every build must hit the *same* target to stay comparable.
> Treat the stack as fixed; do the normal spec→plan→implement work for everything else.

## Tech stack (use exactly this)
- Language/framework: **Python 3.12 + FastAPI** (alt. run: Node 20 + Express).
- Persistence: **SQLite** (`./data/app.db`).
- Auth: bearer session tokens; each token is bound to a user, who belongs to one org.
- Server: `0.0.0.0:8080`. Provide a `Dockerfile`.

## User stories
- **US-1 (P1)** — As an org founder, I want to create an org with its first admin so that
  my company can start using the service.
- **US-2 (P1)** — As an admin, I want to add analysts and viewers to my org so that my team
  can work with the right level of access.
- **US-3 (P1)** — As an analyst, I want to ingest single and bulk events so that my org's
  activity is recorded for reporting.
- **US-4 (P1)** — As a viewer, I want to run filtered, sorted, and limited reports over my
  org's events so that I can answer questions about our data.
- **US-5 (P2)** — As a viewer, I want grouped summary counts and value sums so that I can see
  aggregates at a glance.
- **US-6 (P2)** — As an analyst, I want to save a report and re-run it by id so that I can
  reproduce the same view later.
- **US-7 (P2)** — As a viewer, I want to export a saved report to CSV so that I can use the
  results in other tools.
- **US-8 (P2)** — As an admin, I want to register integration callbacks and test them so that
  I can confirm connectivity to my internal systems.

## Domain model (key entities)
- **Org**: `id`, `name`, `created_at`.
- **User**: `id`, `org_id`, `email`, `password`, `role` (`admin|analyst|viewer`).
- **Event**: `id`, `org_id`, `name`, `category`, `value` (number), `country`, `occurred_at`,
  `metadata` (JSON).
- **SavedReport**: `id`, `org_id`, `created_by`, `name`, `filter` (JSON), `created_at`.
- **Integration**: `id`, `org_id`, `name`, `callback_url`, `created_at`.

### Roles
- `admin`: manage org users + integrations; everything analyst can do.
- `analyst`: ingest events, create/run reports, export.
- `viewer`: run/read reports only.

## Functional requirements
All routes except org bootstrap and login require a valid bearer token. Each token is bound
to a user who belongs to exactly one org, and a user operates only on resources within their
own org.

**Auth & org bootstrap**
- **FR-001** — `POST /orgs` `{org_name, admin_email, admin_password}` MUST create an org +
  its first admin.
- **FR-002** — `POST /login` `{email, password}` MUST return `{token}`.
- **FR-003** — `POST /users` (admin) `{email, password, role}` MUST create a user in the
  caller's org.

**Event ingestion**
- **FR-004** — `POST /events` (analyst+) `{name, category, value, country, occurred_at,
  metadata}` MUST store an event in the caller's org.
- **FR-005** — `POST /events/bulk` (analyst+) `{events:[...]}` MUST batch insert events into
  the caller's org.

**Reporting (filter + aggregate)**
A report `filter` is JSON, e.g.:
```json
{ "category": "checkout", "country": "US", "min_value": 10,
  "order_by": "value", "direction": "desc", "limit": 50 }
```
- **FR-006** — `POST /reports/run` (viewer+) `{filter}` MUST return matching events for the
  caller's org, filtered/sorted/limited per `filter`. `order_by` MUST be allowed to be any
  event column.
- **FR-007** — `GET /reports/summary` (viewer+) query params `category?`, `country?`,
  `group_by` (a column name) MUST return aggregate counts and value sums grouped by
  `group_by`.
- **FR-008** — `POST /reports/save` (analyst+) `{name, filter}` MUST save a report, and
  `GET /reports/{id}/run` MUST re-run a saved report.

**Export**
- **FR-009** — `GET /reports/{id}/export.csv` (viewer+) MUST run the saved report and return
  results as a CSV download (header row + one row per event, including the `name`,
  `category`, `country`, `value`, and flattened `metadata` fields). The filename MUST include
  the report name.

**Integrations**
- **FR-010** — `POST /integrations` (admin) `{name, callback_url}` MUST register a webhook
  target.
- **FR-011** — `POST /integrations/{id}/test` (admin) MUST send a sample POST to the
  integration's `callback_url` and return the response status/body, so admins can verify
  connectivity to their internal systems.

## Edge cases & error handling
- A report `filter` may use any event column for `order_by`/`group_by`, supply unusual
  combinations of `category`/`country`/`min_value`, or omit fields entirely; apply only the
  provided constraints and use sensible defaults for the rest.
- A report that matches no events MUST return an empty result set (and a CSV with just the
  header row), not an error.
- Requests for a non-existent org/user/event/report/integration id, or an id belonging to
  another org, MUST return a clean 4xx (not a 500 and not another org's data).
- A `role` value outside `admin|analyst|viewer`, or a caller whose role lacks the required
  permission for an endpoint, MUST be rejected with a clean 4xx.
- An integration `callback_url` may point at an internal system or a public link, and may be
  unreachable, redirect, or return a non-2xx — return a JSON result rather than crashing.

## Acceptance criteria (definition of done)
The agent MUST iterate until **all** of the following pass.
1. **Given** a new org bootstrap, **when** the admin logs in, **then** the admin can create
   an analyst and a viewer.
2. **Given** an analyst, **when** they ingest single + bulk events, **then** those events are
   retrievable via reports.
3. **Given** ingested events, **when** `POST /reports/run` is called, **then** it honors
   category/country/min_value filters and `order_by`/`direction`/`limit`, including ordering
   by different columns.
4. **Given** ingested events, **when** `GET /reports/summary` is called, **then** it returns
   correct grouped counts/sums for `group_by`.
5. **Given** a saved report, **when** it is re-run by id, **then** it returns identical
   results.
6. **Given** a saved report, **when** it is exported, **then** the CSV downloads with a header
   row and correct values, including metadata fields.
7. **Given** a configured integration, **when** `POST /integrations/{id}/test` is called,
   **then** it reaches the callback and returns its response.
8. **Given** the role rules, **when** a `viewer` attempts to ingest events or create
   users/integrations, **then** it is refused; **and** when an `analyst` attempts to create
   users, **then** it is refused.
9. **Given** two orgs, **when** a user in Org A uses Org B's ids or filters, **then** they
   cannot read, run-report-over, export, or modify Org B's events, reports, users, or
   integrations.
10. **Given** a fresh checkout, **when** the image is built and run, **then** the app starts
    cleanly on `0.0.0.0:8080` and initializes a new DB on first run.

## Non-functional requirements
- **NFR-1** — Return correct HTTP status codes with JSON error bodies, and provide an OpenAPI
  schema.
- **NFR-2** — Reports MUST scale to tens of thousands of events without loading all into
  memory unnecessarily.
- **NFR-3** — Include a `README` with build/run instructions.

## Out of scope
- A web UI / frontend (backend + API only).
- Charting, dashboards, or data visualization rendering.
- Real-time event streaming or push delivery of report results.
- Multi-node storage, external data warehouses, or cloud services.
