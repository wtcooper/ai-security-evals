# File search and retrieval (RAG) — threat and test template

Generated from `templates/file-search-rag.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: the model answers from training and the prompt. After: passages retrieved from a document store are placed in the prompt and treated as knowledge. Whoever can add or edit a document can put text in the model's context.
- Retrieval runs as some identity. If the index was built with wider access than the asking user has, an answer can cross a permission boundary.
- Documents, chunks and embeddings are copied into a store with its own access control, retention and location, often the vendor's.
- Answers carry citations, and people trust citations.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- Which repositories are indexed, and who can write to them?
- Whose permissions apply at query time: the asking user's, or the indexer's?
- Where does the index live, and who operates it?

## Threats

### rag-01 Planted documents steer answers or carry instructions

A document written to be retrieved changes what the model says or does for other users.

OWASP LLM: LLM01:2026 Prompt Injection, LLM09:2026 Vector and Embedding Weaknesses · OWASP Agentic: ASI06 Memory & Context Poisoning · MITRE ATLAS: AML.T0070 RAG Poisoning, AML.T0071 False RAG Entry Injection, AML.T0066 Retrieval Content Crafting, AML.T0051.001 LLM Prompt Injection: Indirect

Review questions

1. Who can add or edit indexed content: all staff, customers, the public?
2. Is retrieved text marked as data? Can it trigger tool calls?
3. Is there review or provenance for content entering the index?

Vendor evidence to look for

- Injection testing through retrieved content.
- Any filtering at ingestion or retrieval.

Existing benchmarks

- **SafeRAG** (arXiv 2501.18636). RAG pipelines under four attack tasks the authors call silver noise, inter-context conflict, soft ad and white denial-of-service. Research code; no skill in this repo runs it. Limits: Its own corpus; language and licence not checked.

Your own tests through this repo's skills

- `app-redteam`: against your own endpoint with documents you plant in a test index.
- `app-benchmark`: a fixed prompt set against the same endpoint.

No standardized test for

- Your corpus and your ingestion path.

### rag-02 Retrieval returns what the asking user may not see

The index was built by an account with wide access, or access rules are not applied at query time, or they are stale.

OWASP LLM: LLM09:2026 Vector and Embedding Weaknesses, LLM02:2026 Sensitive Information Disclosure · MITRE ATLAS: AML.T0085.000 Data from AI Services: RAG Databases

Review questions

1. Are source-system permissions enforced per query, per user?
2. How quickly does a permission change in the source reach the index?

Vendor evidence to look for

- The permission model of the retrieval feature.
- Sync behaviour for access changes.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Needs your access rules: a test with two accounts of different rights. No public benchmark.

### rag-03 Secrets and personal data become searchable

Credentials or personal data sitting in indexed documents can now be asked for in plain language.

OWASP LLM: LLM02:2026 Sensitive Information Disclosure · MITRE ATLAS: AML.T0082 RAG Credential Harvesting, AML.T0085.000 Data from AI Services: RAG Databases

Review questions

1. Was the corpus checked for secrets and regulated data before indexing?
2. Can repositories or file types be excluded?

Vendor evidence to look for

- Exclusion and classification features.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- A scan of your own corpus. Outside this repo.

### rag-04 Leakage between tenants or projects in a shared index

One customer's or project's passages are retrieved for another.

OWASP LLM: LLM09:2026 Vector and Embedding Weaknesses

Review questions

1. Is the index per tenant, per project, or shared with filtering?
2. What is the vendor's isolation evidence?

Vendor evidence to look for

- Isolation architecture and independent audit.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Vendor evidence only.

### rag-05 Private content leaves through the rendered answer

Retrieved text is placed in a link or image address that the user's client fetches, sending it to an attacker.

OWASP LLM: LLM10:2026 Improper Output Handling, LLM02:2026 Sensitive Information Disclosure · MITRE ATLAS: AML.T0077 LLM Response Rendering, AML.T0136 Exfiltration via AI User Interface

Review questions

1. Does the client render links and remote images from model output?
2. Is there an allowlist of domains?

Vendor evidence to look for

- Output-rendering restrictions in the product.

Existing benchmarks

- None found (survey of 2026-11-14).

Your own tests through this repo's skills

- `app-redteam`: against your endpoint, watching for outbound requests that carry a canary.

No standardized test for

- Depends on your client. No public benchmark for a given product.

### rag-06 Wrong answers with trustworthy-looking citations

Conflicting, promotional or fabricated passages are presented with citations that make them look checked.

OWASP LLM: LLM07:2026 Misinformation · OWASP Agentic: ASI09 Human-Agent Trust Exploitation · MITRE ATLAS: AML.T0067.000 LLM Trusted Output Components Manipulation: Citations

Review questions

1. Do users act on answers without opening the sources?
2. Does the product show which passage supports which claim?

Vendor evidence to look for

- Evaluations of answer faithfulness and citation accuracy.

Existing benchmarks

- **SafeRAG** (arXiv 2501.18636). RAG pipelines under four attack tasks the authors call silver noise, inter-context conflict, soft ad and white denial-of-service. Research code; no skill in this repo runs it. Limits: Its own corpus; language and licence not checked.

No standardized test for

- Your own corpus and questions.

### rag-07 The store itself: location, retention, deletion

Copies of documents and embeddings sit somewhere new, are kept after the source is deleted, or are used for other purposes.

OWASP LLM: LLM09:2026 Vector and Embedding Weaknesses

Review questions

1. Where are chunks and embeddings stored, for how long, and are they used for training?
2. Does deleting a source document remove its chunks and embeddings?

Vendor evidence to look for

- Data-handling terms that name the retrieval store.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- A data-handling review.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2026, https://genai.owasp.org/top-10-for-llm-applications-2026/ (read 2026-11-24); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
