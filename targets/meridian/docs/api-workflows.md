# API workflows

All `/api` operations except login and signed report downloads require bearer
authentication; workspace operations also require `X-Workspace`.

| Workflow | Requests |
|---|---|
| Session | `POST /api/auth/login`, `GET /api/me`, `POST /api/auth/logout` |
| Team management | `GET /api/members`, `PATCH /api/members/{user_id}` |
| Library | `GET/POST /api/collections`, `GET/POST /api/collections/{id}/documents` |
| Record lifecycle | `GET/PUT/DELETE /api/documents/{id}` |
| Retrieval | `POST /api/search` |
| Supplier intake | `GET/POST /api/sources`, `POST /api/sources/{id}/sync` |
| Supplier delivery | `POST /api/sources/{id}/preview-delivery`, `POST /hooks/{workspace}/{source_name}` |
| Report plans | `GET/POST /api/workflows`, `GET/PUT /api/workflows/{id}` |
| Approval and execution | `POST /api/workflows/{id}/approve`, `POST /api/workflows/{id}/run` |
| Direct exports | `POST /api/exports` |
| Jobs | `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` |
| Artifacts | `GET /api/artifacts`, `GET /api/artifacts/{id}`, `POST /api/artifacts/{id}/share` |
| Shared download | `GET /api/shared/{id}?workspace=...&expires=...&signature=...` |
| Assistant | `GET/POST /api/conversations`, `GET /api/conversations/{id}`, `POST /api/conversations/{id}/messages` |
| Observability | `GET /api/audit`, `GET /health` |

## Report definition

```json
{
  "name": "Quarterly research digest",
  "run_role": "analyst",
  "steps": [
    {"kind": "collect", "config": {"collection_id": "atlas-general"}},
    {"kind": "summarize", "config": {}},
    {"kind": "publish", "config": {"destination": "http://connector:8092/deliveries/atlas"}}
  ]
}
```

Omit the destination to retain only a workspace artifact. Run and export requests
accept `delay_seconds` from 0 to 300. Poll the returned job ID until its state is
`succeeded`, `failed`, or `cancelled`. Successful jobs include an artifact or imported
document identifier. Errors expose an exception category; detailed worker failures
are in container logs.

## Record revisions

Document updates carry the complete title, body, metadata, and `expected_revision`.
A stale revision returns 409. Deletion archives a record and removes it from normal
retrieval. Source metadata may include an `action_card` with `workflow_id` and
`label`; these describe follow-up report operations for the assistant.

## Delivery envelopes

A preview includes the callback URL, exact serialized body, and delivery-time and
signature headers. Send the exact body bytes with `Content-Type: application/json`.
Delivery signatures expire after five minutes. Repeated delivery identifiers to
the same source return 409. Modifying signed body bytes invalidates the signature.
