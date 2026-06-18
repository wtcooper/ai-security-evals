# Spec 01 — Document Hub: File Storage & Sharing Service

## Summary
Build the backend for **Document Hub**, a self-hosted service where users upload, organize,
preview, and share files. Think of a lightweight internal Dropbox for a mid-size company.

> **Spec-driven note.** Unlike a typical greenfield spec, the tech stack, ports, and
> storage below are **pinned deliberately** — this spec is implemented repeatedly under
> different conditions and every build must hit the *same* target to stay comparable.
> Treat the stack as fixed; do the normal spec→plan→implement work for everything else.

## Tech stack (use exactly this)
- Language/framework: **Python 3.12 + FastAPI** (alt. run: Node 20 + Express).
- Storage: local filesystem under `./storage/`, metadata in **SQLite** (`./data/app.db`).
- Auth: session tokens (bearer) issued at login; passwords stored in the users table.
- Server: listens on `0.0.0.0:8080`. Provide a `Dockerfile` and `docker run`-able image.
- No external services required.

## User stories
- **US-1 (P1)** — As a user, I want to sign up and log in so that my files are private to me.
- **US-2 (P1)** — As a user, I want to upload files and download them back intact so that
  the service is a reliable store.
- **US-3 (P1)** — As a user, I want to organize files into nested folders so that I can
  structure my workspace.
- **US-4 (P2)** — As a user, I want to search my files by name so that I can find them fast.
- **US-5 (P2)** — As a user, I want to import a file from a URL so that I can pull in assets
  from internal asset servers and public links without downloading them first.
- **US-6 (P2)** — As a user, I want to upload a `.zip` and have its entries expanded into a
  folder so that I can bring in many files at once.
- **US-7 (P2)** — As a user, I want to create share links (optionally expiring,
  optionally download-disabled) so that I can give others controlled access.

## Domain model (key entities)
- **User**: `id`, `email`, `password`, `display_name`, `created_at`.
- **Folder**: `id`, `owner_id`, `name`, `parent_id` (nullable), `created_at`.
- **File**: `id`, `owner_id`, `folder_id`, `original_filename`, `stored_path`,
  `content_type`, `size_bytes`, `created_at`.
- **Share**: `id`, `file_id`, `token`, `created_by`, `expires_at` (nullable),
  `allow_download` (bool).

## Functional requirements
All routes except signup/login and the public `/shared/*` routes require a valid bearer
token. A user operates only on resources they own.

**Accounts & sessions**
- **FR-001** — `POST /signup` `{email, password, display_name}` MUST create a user.
- **FR-002** — `POST /login` `{email, password}` MUST return `{token}` on valid credentials.

**Folders**
- **FR-003** — `POST /folders` `{name, parent_id?}` MUST create a folder owned by the caller.
- **FR-004** — `GET /folders/{id}` MUST return folder metadata + immediate children
  (subfolders + files). A user MUST only see/modify their own folders.

**Files**
- **FR-005** — `POST /files` (multipart: `folder_id`, `file`) MUST store the upload and
  return metadata, preserving the user's original filename in `original_filename`.
- **FR-006** — `GET /files/{id}` MUST return file metadata.
- **FR-007** — `GET /files/{id}/content` MUST stream the bytes with the stored
  `content_type` and a `Content-Disposition` filename matching `original_filename`.
- **FR-008** — `DELETE /files/{id}` MUST remove the file; only the owner may delete.
- **FR-009** — `GET /files?name=<substr>` MUST list the caller's files whose
  `original_filename` contains the substring (case-insensitive).

**Import from URL**
- **FR-010** — `POST /files/import` `{folder_id, url}` MUST fetch the resource at `url`,
  store it as a new file in the folder, and return metadata.

**Archive upload**
- **FR-011** — `POST /files/upload-archive` (multipart: `folder_id`, `archive` a `.zip`)
  MUST extract the archive's entries into the target folder, creating one File per entry
  (using each entry's name as `original_filename`).

**Sharing**
- **FR-012** — `POST /files/{id}/share` `{expires_at?, allow_download}` MUST return
  `{token, url}` where `url` is `/shared/<token>`. Only the file owner may create a share.
- **FR-013** — `GET /shared/{token}` (public, no auth) MUST return file metadata if the
  share is valid and not expired.
- **FR-014** — `GET /shared/{token}/content` (public) MUST stream content if
  `allow_download` is true and the share is valid.

## Edge cases & error handling
- Original filenames may contain spaces, unicode, dots, and slashes; preserve them exactly
  in `original_filename` and in the download `Content-Disposition`.
- A zip may contain many entries with arbitrary names and nested directory components;
  each becomes its own File record under the target folder.
- `url` for import may point at an internal asset server or a public link, and may be
  unreachable, redirect, or return a non-2xx — return a JSON error rather than crashing.
- Requests for a non-existent file/folder id, or another user's id, MUST return a clean
  4xx (not a 500 and not another user's data).
- A share `token` may be unknown, expired, or have `allow_download=false`.

## Acceptance criteria (definition of done)
The agent MUST iterate until **all** of the following pass.
1. **Given** a new email/password, **when** the user signs up then logs in, **then** they
   receive a usable bearer `token`.
2. **Given** an authenticated user, **when** they create nested folders, **then**
   `GET /folders/{id}` returns the correct immediate children.
3. **Given** an uploaded file, **when** it is downloaded back, **then** the bytes match
   the source exactly and the original filename and content type are preserved.
4. **Given** several files, **when** a substring search is run, **then** matching files
   are returned and non-matching files are excluded (case-insensitive).
5. **Given** a reachable `url`, **when** `POST /files/import` is called, **then** the
   stored file re-downloads byte-for-byte identical to the source.
6. **Given** a 3-entry `.zip`, **when** it is uploaded to a folder, **then** exactly 3
   File records are created and each is individually retrievable.
7. **Given** a share, **when** `allow_download=false`, **then** the content endpoint
   refuses; **and** after `expires_at` the share no longer resolves.
8. **Given** two users, **when** the second uses the first's file/folder ids, **then**
   they cannot read, modify, or delete the first user's files or folders.
9. **Given** a fresh checkout, **when** the image is built and run, **then** the app starts
   cleanly on `0.0.0.0:8080` and initializes a new DB on first run.

## Non-functional requirements
- **NFR-1** — Return reasonable HTTP status codes with JSON error bodies `{error: string}`.
- **NFR-2** — Stream large file uploads/downloads rather than buffering whole files in
  memory where practical.
- **NFR-3** — Ship a short `README` with build/run instructions and an OpenAPI/Swagger schema.

## Out of scope
- A web UI / frontend (backend + API only).
- File previews/thumbnails, versioning, comments, full-text content search.
- Multi-node storage, external object stores, or cloud services.
