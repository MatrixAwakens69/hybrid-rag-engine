# Hybrid RAG Engine — Implementation Plan

## 1. Purpose

This document is the delivery plan for a production-oriented, multi-tenant document
question-answering service. The system ingests PDFs, tables, plain text, and logs;
retrieves evidence with dense and sparse search; reranks candidates; and returns a
schema-validated answer with citations or an explicit abstention.

The initial delivery is constrained to Python, FastAPI, Qdrant, LlamaIndex, RAGAS,
and Docker. Supporting Python libraries may provide parsing, models, testing,
configuration, and telemetry, but no additional infrastructure service is required.
See [ARCHITECTURE.md](ARCHITECTURE.md) for system design and decision rationale.

## 2. Delivery Principles

- Ship a working, testable vertical slice at the end of each week.
- Treat tenant isolation, deletion, citations, and evaluation as core behavior.
- Keep project-owned interfaces around parsers, embedders, rerankers, generators,
  and storage so model or framework changes do not spread through the codebase.
- Prefer deterministic IDs and idempotent operations over distributed transactions.
- Never return an answer when the available evidence does not support one.
- Gate releases on functional tests, retrieval quality, groundedness, and operability.
- Record the model, prompt, parser, chunker, index, and evaluation dataset versions
  used for every release.

## 3. Scope and Release Boundary

### Version 1 includes

- Tenant-scoped API-key authentication and authorization.
- Asynchronous ingestion of PDF, CSV, Markdown, text, and log files.
- Structure-aware PDF/table extraction with Docling.
- Deterministic, structure-aware chunking with source-location metadata.
- Dense and sparse Qdrant indexes with metadata filtering and reciprocal-rank fusion.
- BGE cross-encoder reranking behind a provider-neutral interface.
- Grounded answer generation with inline citations and Pydantic validation.
- Document status, listing, deletion, query, health, and readiness APIs.
- RAGAS-based regression evaluation and deterministic retrieval tests.
- Docker images, local Compose topology, production configuration, and runbooks.

### Version 1 deliberately excludes

- A browser UI, conversational memory, agentic tool use, and user-generated plugins.
- OCR-heavy handwritten-document guarantees and image understanding beyond
  Docling's supported extraction.
- Cross-tenant retrieval, public document sharing, and per-user ACLs inside a tenant.
- A second vector database implementation.
- Multi-region active-active deployment.
- Unbounded ingestion worker horizontal scaling. Version 1 uses one worker per
  deployment because the allowed stack does not include a transactional queue.

### Production boundary

The first production topology is a hardened single-host Docker deployment with
persistent volumes and external TLS termination. It can serve multiple tenants but
is not presented as a highly available cluster. Multi-host storage, identity
federation, and a durable distributed work queue are explicit scale-out triggers,
not hidden assumptions.

## 4. Target Service-Level Objectives

Initial targets must be verified on representative production hardware and corpus
sizes before launch:

- Query API availability: 99.5% monthly, excluding announced maintenance.
- Query latency: p95 at or below 5 seconds and p99 at or below 10 seconds for
  non-streaming requests with a warm model and index.
- Retrieval latency: p95 at or below 1.5 seconds for the agreed benchmark corpus.
- Ingestion acknowledgement: p95 at or below 500 milliseconds; processing is async.
- Ingestion success: at least 99% for supported, non-corrupt fixture documents.
- Tenant isolation: zero cross-tenant results in automated adversarial tests.
- Recovery point objective: at most 24 hours for indexed data and source files.
- Recovery time objective: at most 4 hours for the initial single-host deployment.

Quality release thresholds are established from the first accepted baseline rather
than invented before a representative golden dataset exists. A release must not
regress retrieval recall, faithfulness, or answer relevancy beyond the policy in
Phase 4.

## 5. Intended Repository Layout

```text
hybrid-rag-engine/
├── app/
│   ├── api/                 # FastAPI routes, dependencies, and error mapping
│   ├── application/         # Ingestion and query use cases
│   ├── domain/              # Models, policies, and project-owned interfaces
│   ├── infrastructure/      # Qdrant, model, parser, and filesystem adapters
│   ├── prompts/             # Versioned prompt templates
│   ├── config.py
│   └── main.py
├── worker/
│   └── main.py              # Ingestion job loop
├── evals/
│   ├── datasets/            # Versioned golden examples
│   ├── baselines/           # Accepted metric snapshots
│   └── run.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── security/
│   ├── performance/
│   └── fixtures/
├── scripts/                 # Backup, restore, reindex, and smoke-test entry points
├── docker/
│   ├── Dockerfile.api
│   └── Dockerfile.worker
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── runbooks/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
└── README.md
```

## 6. Phase-wise Delivery Plan

## Phase 0 — Foundations and Contracts

**Timing:** Week 1, days 1–2

**Goal:** Establish enforceable boundaries and a reproducible development baseline
before implementing retrieval behavior.

### Deliverables

1. Initialize the Python project and pin runtime and development dependencies in
   `pyproject.toml` with a lock file generated by the selected Python package tool.
2. Add linting, formatting, static type checking, unit testing, and coverage commands.
3. Define environment-based settings with Pydantic:
   - service environment and log level;
   - Qdrant endpoint, collection alias, and timeout;
   - source/job volume paths;
   - model adapter names and model revisions;
   - retrieval candidate counts, RRF constant, rerank count, and score thresholds;
   - upload limits, timeouts, and API-key bootstrap settings.
4. Define versioned Pydantic contracts for:
   - tenant principal;
   - document upload acknowledgement and processing status;
   - document metadata and deletion result;
   - query request, cited evidence, answer, abstention, and error;
   - ingestion job state and index manifest.
5. Define project-owned protocols for parser, chunker, dense embedder, sparse
   embedder, reranker, generator, document repository, and retrieval index.
6. Create the FastAPI application factory with request IDs, structured JSON logs,
   centralized error mapping, and `/health/live` and `/health/ready`.
7. Add Docker development services for API, worker, and Qdrant with health checks
   and named persistent volumes.
8. Add CI stages for dependency installation, lint, type checks, unit tests,
   contract validation, image build, and secret scanning.
9. Write a compact threat model covering malicious files, prompt injection,
   cross-tenant access, oversized requests, unsafe logs, and denial of service.

### Tests and evidence

- Configuration tests reject missing secrets and invalid production defaults.
- OpenAPI snapshot tests detect accidental contract changes.
- Health tests distinguish process liveness from dependency readiness.
- Architecture dependency tests prevent API and domain code from importing concrete
  Qdrant, Docling, or model implementations directly.
- Docker smoke test starts all services and verifies API readiness.

### Exit gate

- A clean checkout can run the same lint, type-check, test, and image-build commands
  locally and in CI.
- The API starts without loading heavyweight models during module import.
- Production mode refuses default keys, writable source-tree paths, and permissive
  CORS configuration.

## Phase 1 — Secure, Idempotent Ingestion

**Timing:** Week 1, days 3–5

**Goal:** Convert supported files into traceable, deterministic chunks without
mixing tenant data or losing source provenance.

### Deliverables

1. Implement tenant API-key authentication:
   - store only strong API-key hashes;
   - attach a tenant principal in one FastAPI dependency;
   - require that dependency on every non-health endpoint;
   - never accept a caller-supplied tenant ID as authority.
2. Implement `POST /v1/documents`, `GET /v1/documents/{document_id}`,
   `GET /v1/documents`, and `DELETE /v1/documents/{document_id}`.
3. Stream uploads to a tenant-scoped quarantine directory while computing a
   checksum. Reject unsupported media types, extension/signature mismatches,
   encrypted files that cannot be opened, path traversal, and configured size limits.
4. Create deterministic IDs from tenant, source checksum, parser version, chunker
   version, and embedding schema version. Repeated submissions return the current
   resource unless `force_reindex` is authorized.
5. Persist a job manifest atomically on the shared volume. The worker claims,
   processes, and archives manifests. Work is at-least-once; every downstream write
   must therefore be idempotent.
6. Implement Docling parsing for PDFs and tabular content. Preserve page, heading,
   table, row/column, and bounding metadata when available.
7. Implement bounded streaming parsers for text, Markdown, CSV, and logs. Record
   encoding fallback and dropped/invalid lines as warnings.
8. Normalize parser output to one document-element model before chunking.
9. Implement deterministic structure-aware chunking:
   - keep headings with their following content;
   - keep table headers with split table segments;
   - use token-aware target and maximum sizes;
   - use small overlap only for prose;
   - do not overlap independent log records;
   - retain exact source spans required for citations.
10. Record lifecycle states: `accepted`, `parsing`, `chunking`, `indexing`, `ready`,
    `failed`, `deleting`, and `deleted`, including safe error codes and warnings.
11. Make deletion remove dense/sparse points, source files, derived artifacts, and
    manifests for only the authenticated tenant.

### Tests and evidence

- Golden parser fixtures cover multi-column PDFs, repeated headers, merged table
  cells, long tables, mixed encodings, malformed logs, and corrupt documents.
- Property tests verify stable chunk IDs, maximum token size, ordering, and source
  span preservation.
- Duplicate-delivery tests prove that rerunning any ingestion stage does not create
  duplicate chunks.
- Security tests cover path traversal, MIME spoofing, decompression bombs within
  supported formats, oversized files, hostile filenames, and cross-tenant IDs.
- Deletion tests verify both retrieval absence and artifact removal.

### Exit gate

- A representative corpus can be uploaded, processed, inspected, re-submitted
  idempotently, and deleted through authenticated APIs.
- Every chunk can be traced back to a tenant, document checksum, page or line range,
  parser version, and chunker version.
- Parse failures are visible as terminal document states and do not crash the worker.

## Phase 2 — Hybrid Retrieval and Reranking

**Timing:** Week 2

**Goal:** Retrieve tenant-scoped evidence with measurable quality and predictable
latency before adding answer generation.

### Deliverables

1. Create versioned Qdrant collections with named dense and sparse vectors and
   payload indexes for `tenant_id`, `document_id`, status, content type, and selected
   user metadata.
2. Publish collection aliases only after schema validation and index warm-up.
3. Implement configurable, batch-oriented dense embedding with normalized vectors,
   model revision capture, bounded retries, timeouts, and no silent dimension change.
4. Implement sparse BM25-style representation compatible with Qdrant sparse vectors.
   Tokenization and sparse-model revision form part of the index schema.
5. Upsert dense vector, sparse vector, chunk text, citation metadata, and version
   metadata as one point per chunk.
6. Implement parallel dense and sparse retrieval with mandatory tenant filters and
   optional document/metadata filters.
7. Fuse ranked lists using reciprocal-rank fusion. Do not compare raw dense and
   sparse scores because their scales are not equivalent.
8. Deduplicate by chunk ID, enforce per-document diversity, and pass a bounded
   candidate set to the reranker.
9. Implement a BGE cross-encoder reranker adapter with batch limits, timeout,
   deterministic model revision, and a configured fallback to fused ordering when
   the reranker is unavailable.
10. Return internal retrieval diagnostics in test/admin mode: source ranks, RRF
    score, rerank score, latency by stage, model/index versions, and applied filters.
11. Add `/v1/search` for retrieval-only inspection and integration testing.
12. Define context assembly limits by token budget, evidence score, source diversity,
    and stable final ordering.

### Tests and evidence

- Unit tests cover RRF math, tie ordering, deduplication, filtering, thresholds,
  diversity, and fallback behavior.
- Integration tests run against a real Qdrant container rather than mocks.
- Adversarial isolation tests attempt cross-tenant query, filter, and document-ID
  access.
- A retrieval fixture set includes exact keyword queries, paraphrases, identifiers,
  table values, log signatures, and no-answer queries.
- Benchmark output records Recall@5, Recall@10, MRR@10, nDCG@10, and p50/p95 latency
  for dense-only, sparse-only, fused, and reranked variants.
- Load tests verify bounded concurrency and memory use at the agreed corpus size.

### Exit gate

- Hybrid retrieval improves the accepted primary retrieval metric over both
  dense-only and sparse-only baselines on the representative fixture set.
- Reranking improves nDCG or MRR without violating the retrieval latency budget.
- Cross-tenant leakage tests return zero unauthorized chunks.
- Reranker failure is observable and degrades to fused retrieval rather than failing
  open or returning unfiltered data.

## Phase 3 — Grounded Generation and Public API

**Timing:** Week 3

**Goal:** Turn ranked evidence into reliable, versioned API responses without hiding
uncertainty or schema failures.

### Deliverables

1. Implement provider-neutral generation and embedding adapters selected through
   configuration. Provider SDK objects remain inside infrastructure modules.
2. Create versioned prompts that:
   - treat retrieved content as untrusted data, not instructions;
   - answer only from supplied evidence;
   - cite stable evidence IDs for every material claim;
   - state when evidence conflicts;
   - abstain when evidence is insufficient.
3. Implement `POST /v1/query` with question, optional document/metadata filters,
   bounded retrieval controls, and a client idempotency/request ID.
4. Define a versioned `AnswerResponse` with answer text, status, evidence list,
   citations, warnings, request ID, and model/index/prompt versions.
5. Validate generated structured output with Pydantic and verify that:
   - every cited ID exists in the supplied context;
   - each citation belongs to the authenticated tenant;
   - answer status and evidence are consistent;
   - response and evidence sizes remain bounded.
6. On invalid output, perform one constrained repair attempt. If repair fails, return
   a typed generation error. If evidence is inadequate, return `abstained` with
   relevant evidence rather than inventing an answer.
7. Implement request timeouts, concurrency limits, body limits, safe CORS defaults,
   per-key rate limiting within the API process, and graceful shutdown.
8. Emit structured operational events without raw document text, prompts, answers,
   API keys, or personally identifiable metadata by default.
9. Include OpenAPI examples for success, abstention, validation failure, processing
   document, missing document, unauthorized access, and rate limiting.

### Tests and evidence

- Contract tests validate all public responses against OpenAPI/Pydantic schemas.
- Generation tests use deterministic fake adapters for valid output, malformed JSON,
  fabricated citation IDs, conflicting evidence, timeout, and empty evidence.
- Prompt-injection fixtures attempt to override system instructions from inside
  documents.
- End-to-end tests upload a document, await readiness, search, query, verify
  citations, delete it, and confirm it can no longer be retrieved.
- Concurrency tests verify rate limiting, timeout propagation, cancellation, and
  graceful worker/API shutdown.
- Logs are scanned to ensure test secrets and fixture content are absent.

### Exit gate

- Every successful factual answer contains verified citations to retrievable source
  spans.
- Unsupported questions reliably abstain in the accepted no-answer fixture set.
- Provider and reranker failures produce documented typed responses and metrics.
- The complete document lifecycle passes in Docker with no manual database changes.

## Phase 4 — Evaluation, Hardening, and Production Release

**Timing:** Week 4

**Goal:** Establish evidence that the service is useful, safe to operate, recoverable,
and resistant to quality regressions.

### Deliverables

1. Create a versioned RAGAS dataset with:
   - representative user questions and reference answers where appropriate;
   - expected source documents or chunks;
   - answerable and deliberately unanswerable examples;
   - PDFs, tables, logs, identifiers, paraphrases, and conflicting evidence;
   - tenant-isolation and prompt-injection cases kept as deterministic security tests.
2. Implement a reproducible evaluation runner that captures dataset revision, random
   seed, application revision, parser/chunker/index schema, model revisions, prompt
   version, metric versions, per-example results, aggregates, latency, and cost when
   exposed by the configured provider.
3. Track RAGAS faithfulness, context recall, and answer relevancy. Pair them with
   deterministic Recall@k, MRR, nDCG, citation validity, abstention precision/recall,
   error rate, and latency so release decisions do not depend on one stochastic score.
4. Establish the first baseline only after domain review of the dataset and a manual
   sample of outputs. Store the accepted summary and configuration in `evals/baselines`.
5. Implement evaluation policy:
   - pull requests run deterministic tests and a small, bounded RAGAS smoke set;
   - scheduled and pre-release jobs run the full dataset;
   - block when deterministic isolation/citation tests fail;
   - block when a primary metric drops more than the agreed absolute tolerance or
     its confidence interval shows a material regression;
   - require human review for threshold overrides and baseline updates.
6. Harden Docker images with pinned bases, multi-stage builds, non-root users,
   read-only root filesystems where practical, dropped capabilities, health checks,
   resource limits, and image/dependency vulnerability scanning.
7. Configure separate development, test, staging, and production settings. Secrets
   are injected at runtime and never baked into images or committed files.
8. Add backup and restore scripts for Qdrant snapshots, source files, manifests,
   tenant key records, and configuration/version manifests.
9. Test blue/green reindexing:
   - build a new versioned collection;
   - verify count, schema, sample retrieval, and evaluation smoke tests;
   - atomically switch the alias;
   - retain the prior collection for a bounded rollback window.
10. Add runbooks for failed ingestion, degraded model provider, Qdrant outage,
    disk pressure, suspected tenant leakage, key rotation, backup restoration,
    reindexing, rollback, and tenant deletion.
11. Produce a release evidence bundle containing test results, evaluation comparison,
    image digests, dependency scan, configuration diff, backup verification, and
    rollback owner.

### Production rollout

1. Freeze the candidate model, prompt, parser, chunker, and index versions.
2. Restore a recent backup into staging and run migration and retrieval checks.
3. Run the full test suite and evaluation suite against the release image.
4. Deploy to staging, ingest a representative corpus, and run API smoke/load tests.
5. Back up production and verify available disk capacity before deployment.
6. Deploy API and worker with the previous version retained.
7. Route internal/canary tenants first and observe errors, latency, abstention, and
   retrieval-empty rates for an agreed soak period.
8. Expand traffic only when canary gates pass.
9. Roll back the application image and collection alias if functional, quality,
   isolation, or latency gates fail.
10. Record release versions and evidence; do not update the quality baseline as part
    of the same unreviewed change.

### Exit gate

- CI, full evaluation, vulnerability scanning, backup/restore, reindex rollback,
  tenant deletion, and incident-tabletop checks pass.
- Dashboards or log queries exist for SLOs and the failure signals listed in the
  architecture document.
- On-call and service owners accept the runbooks and rollback procedure.
- A canary deployment completes without an unexplained metric regression.

## 7. Test Strategy

### Unit tests

Run on every change and avoid network/model calls. Cover domain policies, IDs,
chunking, fusion, citation checks, state transitions, validation, and failure mapping.

### Contract tests

Run on every change. Snapshot OpenAPI intentionally, validate serialized responses,
and require an explicit API version or compatibility review for breaking changes.

### Integration tests

Run against disposable Qdrant and real filesystem volumes in Docker. Exercise
collection creation, payload indexes, tenant filters, alias swaps, deletion,
snapshots, and worker retry behavior.

### End-to-end tests

Run in CI for a compact corpus and before release for the full representative corpus.
Use real service containers but replace paid/nondeterministic model calls with fixed
adapters in the fast suite. A controlled live-model suite runs pre-release.

### Security tests

Cover authentication, authorization, object reference attacks, tenant-filter
omission, malicious filenames/files, upload limits, prompt injection, citation
forgery, secret leakage, dependency scanning, and container privileges.

### Performance and resilience tests

Measure indexing throughput, API concurrency, p50/p95/p99 latency, memory, model
batching, disk growth, Qdrant interruption, model timeout, process restart, duplicate
job delivery, and graceful shutdown. Performance baselines use fixed hardware and
corpus manifests.

## 8. CI/CD Gates

The pipeline progresses from fastest and most deterministic to slower and more
expensive checks:

1. Dependency integrity, lint, formatting, type checks, and architecture boundaries.
2. Unit, contract, and security tests with coverage thresholds focused on critical
   policies rather than a vanity repository-wide percentage.
3. Integration and compact end-to-end tests with disposable Docker services.
4. Deterministic retrieval and citation regression suite.
5. Bounded RAGAS smoke evaluation for relevant changes.
6. Docker build, software bill of materials, vulnerability scan, and startup smoke.
7. Staging deployment, migrations/reindex checks, and smoke tests.
8. Manual production approval with release evidence.
9. Canary rollout followed by automated health checks and an explicit promotion.

Changes limited to documentation may skip model evaluations. Changes to parser,
chunker, embedding, sparse representation, fusion, reranking, prompt, generator, or
evaluation code must run the corresponding quality suite.

## 9. Observability and Operational Readiness

Before production, expose or derive:

- request count, error rate, and latency by route and response status;
- authentication failures and rate-limit rejections;
- ingestion queue depth, job age, duration by stage, failures, and retry count;
- parsed pages/elements, chunk count and size distributions, and warning rates;
- dense, sparse, fusion, rerank, generation, and total query latency;
- empty retrieval, low-confidence, abstention, invalid-output, repair, and fallback
  rates;
- Qdrant health, storage growth, snapshot age, collection point count, and alias;
- active application, model, prompt, parser, chunker, and index versions.

Logs use request, tenant-safe, document, and job correlation IDs. Tenant IDs should
be pseudonymous in shared operational views. Raw source and answer content is opt-in
for a controlled diagnostic workflow, never default telemetry.

## 10. Post-deployment Maintenance

### Daily

- Review SLO breaches, high-severity errors, oldest ingestion jobs, disk capacity,
  provider failures, and backup completion.
- Investigate sudden changes in empty retrieval, abstention, or validation repair.

### Weekly

- Triage failed documents and add sanitized regression fixtures for new parser cases.
- Review slow queries, hot tenants, index growth, and reranker fallback.
- Sample cited answers for grounding and citation usefulness.

### Monthly

- Run the full evaluation suite and compare corpus segments, not only aggregate means.
- Restore a backup in an isolated environment and record recovery duration.
- Review dependencies, base images, vulnerabilities, API keys, and access logs.
- Validate tenant deletion and expired-artifact cleanup.
- Review capacity headroom and SLO/error-budget consumption.

### Quarterly

- Reassess model, prompt, parser, chunker, and sparse-index versions one variable at
  a time against the frozen baseline.
- Conduct a tenant-isolation and prompt-injection exercise.
- Exercise collection rollback and document reindex procedures.
- Review golden-dataset representativeness, stale examples, and annotation quality.
- Revisit architecture decisions whose triggers have been reached.

### Safe model or index upgrade

1. Pin the candidate revision; never use a floating production model identifier.
2. Build a new collection if embeddings, dimensions, tokenization, sparse model,
   parser, or chunker semantics change.
3. Run deterministic retrieval, RAGAS, performance, and manual sample review.
4. Canary the candidate against selected tenants or shadow queries.
5. Switch the Qdrant alias only after all gates pass.
6. Retain the prior collection and application image through the rollback window.
7. Update the baseline only through a separately reviewed change.

## 11. Definition of Done

The project is production-ready for the stated single-host, multi-tenant boundary
when:

- all public APIs are authenticated, versioned, documented, and contract-tested;
- ingestion is safe, idempotent, observable, recoverable, and supports deletion;
- every storage and retrieval operation proves tenant scoping;
- hybrid retrieval and reranking beat accepted baselines within latency budgets;
- successful answers have validated citations and unsupported questions abstain;
- tests, RAGAS evaluation, image security, backup restoration, and rollback pass;
- production configuration contains no development defaults or committed secrets;
- release, incident, reindex, restore, key rotation, and deletion runbooks have owners;
- post-release SLOs, evaluation cadence, and architecture revisit triggers are agreed.
