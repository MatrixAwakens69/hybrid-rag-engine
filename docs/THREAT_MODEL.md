# Phase 0 Threat Model

## Scope

This threat model covers the initial multi-tenant Hybrid RAG Engine boundary:
FastAPI, the ingestion worker, persistent source/job storage, Qdrant, configured
model endpoints, and operator-controlled backups.

It records planned controls even when their implementation belongs to a later phase.
Only controls marked **Phase 0 implemented** may be treated as present now.

## Assets

- tenant API keys and operator secrets;
- source documents, parsed text, chunks, and embeddings;
- tenant and document identifiers;
- Qdrant collections, aliases, control records, and snapshots;
- prompts, model/provider credentials, and generated answers;
- job manifests, logs, evaluation datasets, and release configuration.

## Trust Boundaries

1. Public callers to the TLS proxy and FastAPI API.
2. Uploaded files and all extracted document content.
3. API/worker containers to Qdrant and persistent volumes.
4. API/worker/evaluation processes to configured model endpoints.
5. Operators to admin workflows, production secrets, backups, and releases.
6. Generated model output back into the application.

Health endpoints are public and expose only service, revision, status, dependency
name, and latency. They never expose configuration values, stack traces, collection
contents, or provider responses.

## Threats and Controls

### Cross-tenant access

Threats:

- forged tenant identifiers;
- object reference attacks with another tenant's document/chunk ID;
- a missing Qdrant tenant filter on search, list, count, update, or delete;
- data exposed during reindex or alias switching.

Controls:

- **Phase 0 implemented:** domain repository/index protocols require an authoritative
  `TenantPrincipal`; tenant IDs are not optional strings.
- **Phase 0 implemented:** strict contracts reject unknown fields.
- **Phase 1 implemented:** API keys are Argon2-hashed and mapped to tenant
  principals at one FastAPI dependency.
- **Phase 1 implemented:** document control reads, lists, status changes, and deletion
  use authoritative tenant principals and tenant-scoped Qdrant access.
- **Phase 2 planned:** mandatory tenant filters and tenant-derived IDs extend to every
  dense/sparse chunk operation.
- **Every phase gate:** adversarial tests for all tenant-scoped operations block
  release.

Residual risk: shared collections make a missing filter high impact. A contractual
requirement for physical tenant isolation triggers dedicated collections or a revised
storage architecture.

### Malicious or malformed files

Threats:

- path traversal, unsafe filenames, MIME spoofing, corrupt/encrypted files;
- decompression bombs, excessive pages/rows/lines, parser exploits, and memory/CPU
  exhaustion;
- persistence of malicious content outside quarantine.

Controls:

- **Phase 0 implemented:** upload, metadata, request timeout, and storage-path limits
  are validated configuration, but no upload route exists yet.
- **Phase 1 implemented:** streaming upload, generated paths, checksums, signature/type
  checks, quarantine, parser limits, terminal failure states, and sandbox-aware
  processing.
- **Phase 4 planned:** hardened containers, vulnerability scanning, resource limits,
  and recovery drills.

Residual risk: Docling and file-format dependencies process attacker-controlled data.
Keep them pinned and patched; never run parser containers with host or Docker-socket
access.

### Prompt injection and untrusted document instructions

Threats:

- retrieved text instructs the model to ignore grounding or reveal secrets;
- documents contain fabricated citation markers;
- generated output references evidence not supplied to the model.

Controls:

- **Phase 0 implemented:** generated answer, evidence, citation, and version contracts
  are strict; answer contracts reject unknown evidence IDs.
- **Phase 3 planned:** delimit content as untrusted evidence, disable tool execution,
  require evidence IDs, validate tenant/evidence membership, repair once, then
  abstain or fail.
- **Phase 3/4 planned:** prompt-injection and unsupported-question regression suites.

Residual risk: no prompt fully eliminates injection. The application must enforce
authorization and citation membership outside the model.

### Oversized requests and denial of service

Threats:

- large or slow uploads, expensive repeated queries, model concurrency exhaustion;
- ingestion backlog, disk exhaustion, unbounded retries, and Qdrant overload;
- health checks causing paid model requests.

Controls:

- **Phase 0 implemented:** bounded settings, a connectivity-only readiness probe, and
  no model calls from health routes.
- **Phase 1 implemented:** streaming size enforcement and bounded parser work.
- **Phase 2/3 planned:** bounded candidate counts, context sizes, timeouts,
  concurrency, and per-key rate limiting.
- **Phase 4 planned:** resource limits, capacity alerts, load tests, and runbooks.

Residual risk: Phase 0 does not expose ingestion/query routes, so configured limits
are not yet enforcement. In-process rate limits will not be global after API
horizontal scaling.

### Unsafe logging and information disclosure

Threats:

- API keys, source text, prompts, answers, personally identifiable information,
  embeddings, provider payloads, or stack traces enter shared logs or responses;
- caller-controlled request IDs inject unsafe log values.

Controls:

- **Phase 0 implemented:** request IDs are allowlisted or regenerated, logs are
  structured, access events contain only method/path/status/duration, and centralized
  errors return safe codes/messages.
- **Phase 0 implemented:** readiness failures expose a generic dependency error.
- **Later phases:** content logging remains opt-in, time-bounded, access-controlled,
  and tenant-approved.

Residual risk: future code can add unsafe fields. Log-content scanning is required in
every phase that introduces document/model behavior.

### Secret compromise

Threats:

- default credentials, committed `.env` files, secrets in images/logs, weak key
  rotation, or provider keys exposed to documents.

Controls:

- **Phase 0 implemented:** secret files are ignored, `.env.example` contains only a
  known development placeholder, production rejects weak bootstrap keys, and images
  receive configuration at runtime.
- **Phase 0 CI:** repository secret scanning blocks new findings.
- **Phase 1 implemented:** hashed tenant keys and scoped bootstrap keys.
- **Phase 4 planned:** formal rotation workflows and runbooks.

Residual risk: `.env.example` intentionally resembles a credential assignment.
Secret scanning must allow documented placeholders without allowing real values.

### Dependency and supply-chain compromise

Threats:

- malicious or vulnerable Python packages, base images, model artifacts, parser
  dependencies, or floating versions.

Controls:

- **Phase 0 implemented:** `uv.lock`, exact Qdrant tag, fixed uv tool image, CI lock
  enforcement, and no heavyweight model dependencies.
- **Phase 4 planned:** base-image digests, SBOM, image/dependency vulnerability gates,
  and pinned model artifact revisions.

Residual risk: Phase 0 Python constraints resolve to exact lock versions but base
images are not yet digest-pinned. Full production hardening remains a Phase 4 gate.

### Data deletion and backup retention

Threats:

- deletion removes metadata but leaves chunks/source files;
- backups retain tenant data beyond communicated policy;
- a cross-tenant filter deletes another tenant's data.

Controls:

- **Phase 0 implemented:** deletion and lifecycle contracts include a retention
  notice and tenant principal.
- **Phase 1 implemented:** idempotent deletion removes active source and derived
  artifacts and reaches a verified terminal lifecycle state.
- **Phase 2 planned:** deletion extends to tenant-filtered dense and sparse points.
- **Phase 4 planned:** documented backup retention, restore tests, and tenant deletion
  drills.

Residual risk: backup erasure is governed by the final retention policy, not immediate
physical deletion.

## Abuse Cases Required in Regression Suites

- another tenant's document ID for get, list, search, count, status, and delete;
- missing/empty/repeated/malformed tenant and metadata filters;
- wildcard CORS and weak production bootstrap secret;
- path traversal, hostile filename, MIME mismatch, corrupt and oversized files;
- document text that requests secret disclosure or policy override;
- model output with unknown or cross-tenant evidence IDs;
- malformed request IDs, provider errors, and parser errors containing sensitive text;
- dependency outage, timeout, duplicate job delivery, and disk pressure.

## Review Cadence

Review this model:

- at every phase boundary;
- whenever a public route, file type, model adapter, infrastructure service, or
  tenant permission is added;
- after a security incident or a high-severity dependency advisory;
- quarterly after production launch.

The service owner accepts residual risk; individual feature authors cannot silently
waive a release-blocking tenant-isolation or citation-integrity failure.
