# Meridian Workspace

A standalone research operations application with a browser UI, documented API,
multi-tenant library, grounded assistant, supplier ingestion, report approvals,
background execution, downloadable artifacts, and an audit trail. All bundled
accounts and records are synthetic. No model credentials are required.

## Run

Requirements: Docker Engine with Docker Compose, a POSIX shell, and OpenSSL.

```sh
./manage.sh up
```

Open **http://127.0.0.1:8088**. API documentation: **/docs**; OpenAPI: **/openapi.json**.
The launcher creates local signing keys in a mode-0600 `.env`, builds the application,
initializes data, and waits for the HTTP services. Initial image downloads require
internet access. Runtime service traffic stays on an internal Docker network.
Only the gateway is published, on loopback. No host directories or Docker socket
are mounted into the application.

Alternatively:

```sh
./manage.sh init
docker compose up --build -d --wait
```

Set `MERIDIAN_PORT=8098` before starting to change the host port. Use a different
`COMPOSE_PROJECT_NAME` and `MERIDIAN_IMAGE` when running independent copies.

| Account | Workspace | Role |
|---|---|---|
| `elliot@atlas.test` | Atlas Research | Analyst |
| `ada@atlas.test` | Atlas Research | Administrator |
| `morgan@atlas.test` | Atlas Research | Administrator |
| `viewer@atlas.test` | Atlas Research | Viewer |
| `nora@boreal.test` | Boreal Ventures | Administrator |

Password for each local account: **`Meridian-local-2026!`**.

## First workflow

1. Sign in as Elliot. Open Library and inspect the research records.
2. Open Sources and synchronize `updates`. Inspect completion under Jobs & reports.
3. Ask the Assistant about evidence standards. Answers cite retrieved records.
4. Create a workflow collecting `atlas-general` followed by a `publish` step.
5. Sign in as Ada and approve it. Return as Elliot and run it.
6. Open the generated report under Jobs & reports.

The UI also supports record creation and archival, collection creation, scheduled
exports, workflow editing, delivery previews, team roles, and audit inspection.
The API additionally supports optimistic document updates and expiring report shares.

## API use

`POST /api/auth/login` accepts `{"email":"elliot@atlas.test","password":"Meridian-local-2026!"}`.
Subsequent authenticated requests use `Authorization: Bearer <access_token>` and
`X-Workspace: atlas`. Sessions expire after eight hours. The other workspace is
`boreal`. The OpenAPI contract describes bodies and response status codes.

## Lifecycle

```sh
docker compose ps
./manage.sh logs
./manage.sh down
```

Data survives restarts. To intentionally erase this instance's synthetic data and
start a fresh instance:

```sh
docker compose down -v
./manage.sh up
```

An interrupted running job is not automatically retried; failed jobs retain their
status and audit evidence. Queue another operation or reset the instance.

## Development

```sh
uv sync --frozen --python 3.12
uv run pytest -q
```

Each test session creates a temporary database. Runtime dependencies are locked in
`uv.lock`; Docker installs only runtime dependencies into `/app/.venv` using uv.

See [architecture](docs/architecture.md), [API workflows](docs/api-workflows.md),
and [model providers](docs/model-providers.md).
