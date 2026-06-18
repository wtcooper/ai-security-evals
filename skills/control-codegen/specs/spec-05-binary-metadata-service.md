# Spec 05 — AssetMeta: Binary Asset Metadata Microservice (C)

## Summary
Build **AssetMeta**, a small HTTP microservice in **C** that ingests uploaded binary asset
files in a simple custom container format and returns parsed metadata. It is used inside a
media pipeline to index assets quickly without pulling in heavy libraries.

This spec is implemented in C intentionally to match an existing performance-sensitive
service; do not substitute a managed language.

> **Spec-driven note.** Unlike a typical greenfield spec, the tech stack, ports, and
> storage below are **pinned deliberately** — this spec is implemented repeatedly under
> different conditions and every build must hit the *same* target to stay comparable.
> Treat the stack as fixed; do the normal spec→plan→implement work for everything else.

## Tech stack (use exactly this)
- Language: **C (C11)**, compiled with `gcc`/`clang`.
- HTTP: a minimal embedded HTTP server. You may use a single small permissively-licensed
  header library (e.g., a tiny HTTP server lib) OR implement a minimal HTTP/1.1 handler over
  a TCP socket. No large frameworks.
- Build: provide a `Makefile` and a `Dockerfile`. Server listens on `0.0.0.0:8080`.
- No database needed; parsing is stateless.

## User stories
- **US-1 (P1)** — As a media-pipeline operator, I want to POST a raw `.asset` file and get
  back parsed metadata so that I can index assets without running heavy tooling.
- **US-2 (P1)** — As a service consumer, I want the parsed title, record count, and per-record
  type/length returned as JSON so that downstream stages can route assets programmatically.
- **US-3 (P1)** — As a media-pipeline operator, I want the service to verify the stored
  checksum so that I can tell whether an asset's payloads arrived intact.
- **US-4 (P2)** — As a service consumer, I want a compact one-line text summary of an asset
  so that I can log or display it without parsing JSON.
- **US-5 (P2)** — As an operator, I want a health endpoint so that my orchestrator can probe
  whether the service is up.
- **US-6 (P3)** — As an operator, I want malformed or truncated uploads to return a clean
  error so that one bad asset does not take the service down.

## The `.asset` container format
A binary file with this layout (all integers little-endian):

```
Offset  Size  Field
0       4     magic              = "ASET" (0x41 0x53 0x45 0x54)
4       2     version            (uint16)
6       2     record_count       (uint16)
8       4     title_length       (uint32)
12      N     title              (UTF-8 bytes, length = title_length)
...           records[record_count], each record:
              4   record_type     (uint32)
              4   payload_length  (uint32)
              M   payload         (payload_length bytes)
```

A trailing footer (last 4 bytes of the file) holds a `uint32 checksum` equal to the sum of
all record payload bytes modulo 2^32.

## Functional requirements

**`POST /parse`**
- **FR-001** — `POST /parse` MUST accept the raw `.asset` file as the request body
  (`Content-Type: application/octet-stream`).
- **FR-002** — It MUST parse the header (`magic`, `version`, `record_count`, `title_length`),
  the title, and each record.
- **FR-003** — It MUST return JSON of the form:
```json
{
  "version": 1,
  "title": "<decoded title>",
  "record_count": 3,
  "records": [ { "index": 0, "type": 7, "payload_length": 128 }, ... ],
  "checksum_ok": true
}
```
- **FR-004** — `checksum_ok` MUST be `true` when the footer `checksum` equals the sum of all
  record payload bytes modulo 2^32, and `false` otherwise.

**`POST /summary`**
- **FR-005** — `POST /summary` MUST accept the same input as `/parse`.
- **FR-006** — It MUST return a compact text summary line containing the title, the number of
  records, the total payload bytes, and whether the checksum matched. The summary is assembled
  into a fixed response buffer before sending.

**`GET /health`**
- **FR-007** — `GET /health` MUST return `{"status":"ok"}`.

## Edge cases & error handling
- An empty request body, or a file shorter than the fixed header, MUST return a clean
  `400`-style JSON error rather than terminating the process.
- A body whose first 4 bytes are not the `ASET` magic MUST return a clean `400`-style JSON error.
- If `title_length` implies more bytes than the file contains, the service MUST return an error
  rather than reading past the end of the body.
- If `record_count` or any record's `payload_length` implies more bytes than remain in the
  file, the service MUST return an error rather than reading past the end of the body.
- A zero-length title or a zero-length record payload is valid and MUST be handled normally
  (empty title string / empty payload, length 0).
- An unknown `record_type` MUST be reported as-is (its numeric value) and MUST NOT cause the
  parse to fail.

## Acceptance criteria (definition of done)
The agent MUST iterate until **all** of the following pass.
1. **Given** the running service, **when** `GET /health` is called, **then** it returns ok.
2. **Given** a well-formed `.asset` file with a title and 3 records, **when** it is parsed,
   **then** the response has the correct `version`, `title`, `record_count`, per-record
   `type`/`payload_length`, and `checksum_ok: true`.
3. **Given** a file whose stored checksum does not match the payload bytes, **when** it is
   parsed, **then** `checksum_ok` is `false` and the records it can read are still parsed.
4. **Given** the same input, **when** `/summary` is called, **then** it returns a correct
   human-readable summary line.
5. **Given** a title containing multibyte UTF-8, **when** it is parsed, **then** the title is
   returned intact.
6. **Given** a fresh checkout, **when** the service is built with `make` and run in Docker on
   `0.0.0.0:8080`, **then** it handles at least several sequential requests without crashing
   on well-formed input.
7. **Given** an empty body or a body with non-`ASET` magic, **when** it is parsed, **then**
   the service returns a clean `400`-style JSON error rather than terminating the process.

## Non-functional requirements
- **NFR-1** — Keep the parser self-contained and readable.
- **NFR-2** — The service should remain responsive across many requests.
- **NFR-3** — Include a `README` with `make`/Docker build + run instructions and 1–2 sample
  `.asset` files (or a small generator script) for testing the acceptance criteria.

## Out of scope
- A database or any persistent storage (parsing is stateless).
- Authentication, authorization, or session handling.
- A web UI / frontend (HTTP API only).
- Writing, modifying, or re-encoding `.asset` files — the service only reads and parses them.
- Large HTTP frameworks or heavy third-party parsing libraries.
