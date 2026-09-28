PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    workspace_id TEXT REFERENCES workspaces(id), user_id TEXT REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('admin','analyst','viewer')),
    PRIMARY KEY(workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), name TEXT NOT NULL,
    access TEXT NOT NULL CHECK(access IN ('team','restricted'))
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, collection_id TEXT REFERENCES collections(id), title TEXT NOT NULL,
    body TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL, created_at REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id), ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(chunk_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS retrieval_cache (
    cache_key TEXT PRIMARY KEY, chunk_ids TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), name TEXT NOT NULL,
    collection_id TEXT REFERENCES collections(id), url TEXT NOT NULL,
    created_by TEXT NOT NULL, UNIQUE(workspace_id, name)
);
CREATE TABLE IF NOT EXISTS hook_deliveries (
    source_id TEXT REFERENCES sources(id), delivery_id TEXT NOT NULL, received_at REAL NOT NULL,
    PRIMARY KEY(source_id, delivery_id)
);
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), owner_id TEXT NOT NULL,
    name TEXT NOT NULL, spec TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
    approved_digest TEXT, approved_by TEXT, approved_at REAL, run_role TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), requested_by TEXT NOT NULL,
    role_snapshot TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued', result TEXT, error TEXT,
    scheduled_at REAL NOT NULL, created_at REAL NOT NULL, started_at REAL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), owner_id TEXT NOT NULL,
    job_id TEXT REFERENCES jobs(id), filename TEXT NOT NULL, media_type TEXT NOT NULL,
    body TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), owner_id TEXT NOT NULL,
    title TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id), role TEXT NOT NULL,
    content TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL,
    action TEXT NOT NULL, resource_id TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state, scheduled_at);
CREATE INDEX IF NOT EXISTS docs_collection ON documents(collection_id, archived);
CREATE INDEX IF NOT EXISTS audit_workspace ON audit_events(workspace_id, id);
