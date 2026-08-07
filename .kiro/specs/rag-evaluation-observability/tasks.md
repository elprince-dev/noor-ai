# Implementation Plan: RAG Evaluation and Observability

## Overview

Implementation proceeds in four layers, each depending on the previous: (1) the trace logging package and its pipeline integration, (2) the versioned golden dataset, (3) the offline eval harness with retrieval and generation metrics, and (4) online metrics infrastructure, the feedback loop, and triage. Backend work is Python (pytest + Hypothesis for property tests), infrastructure is TypeScript CDK (Jest + aws-cdk-lib/assertions), and frontend is TypeScript/React. All property tests run against pure functions or constructor-injected in-memory fakes — no AWS calls.

## Tasks

- [x] 1. Observability package foundations
  - [x] 1.1 Create `backend/src/observability/` package with trace data models and structured logging helper
    - Create `__init__.py`, `models.py` with immutable `Trace`, `RetrievalRecord`, `CostEstimate`, `ModelPricing` types carrying `schema_version: 1`
    - Create `logging.py` with `log_json(level, message, **fields)` that auto-injects `request_id` from the current trace context
    - Set up `backend/tests/observability/` test directory
    - _Requirements: 2.7, 1.4_

  - [x] 1.2 Implement `TraceContext` request-scoped accumulator in `trace_context.py`
    - `_current_trace` ContextVar + `TraceContext.current()` classmethod for async-safe propagation
    - Generate `request_id` (uuid4) and UTC `received_at` in the constructor, before any pipeline step
    - Recording methods: `record_retrieval(chunks, latency_ms)`, `mark_first_token()` (sets `ttft_ms` once), `record_prompt(messages)`, `record_usage(input_tokens, output_tokens)`, `record_response(answer)`, `record_failure(step, error)`, plus `current_step` tracking
    - `build_trace(cost)` freezes accumulated state into the immutable `Trace` model; missing token counts stay `None`, TTFT stays `None` when never marked
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.6, 2.10_

  - [x] 1.3 Write property test for trace completeness on success
    - **Property 3: Trace completeness for successful requests**
    - **Validates: Requirements 2.1, 2.4, 2.7**

  - [x] 1.4 Write property test for retrieval recording fidelity
    - **Property 4: Retrieval recording fidelity**
    - **Validates: Requirements 2.2**

  - [x] 1.5 Write property test for response assembly fidelity
    - **Property 5: Response assembly fidelity**
    - **Validates: Requirements 2.3**

- [x] 2. Cost estimation, truncation, sink, and trace repository
  - [x] 2.1 Implement `CostEstimator` in `cost.py` and add `MODEL_PRICING` to `backend/src/config.py`
    - Pure `estimate(input_tokens, output_tokens, model_id) -> CostEstimate`; pricing table injected via constructor
    - Substring lookup against configured model ID (handles cross-region `us.` prefixes); returns not-computed when either token count is `None` or no pricing entry matches — never zero or substituted
    - Add `MODEL_PRICING: dict[str, ModelPricing]` with the Claude Haiku 4.5 entry to `config.py`
    - _Requirements: 2.5, 2.8, 2.9_

  - [x] 2.2 Write property test for cost estimation
    - **Property 6: Cost estimation correctness**
    - **Validates: Requirements 2.5, 2.8, 2.9**

  - [x] 2.3 Implement `TraceTruncator` in `truncation.py`
    - Pure `truncate_to_fit(trace) -> Trace` with `max_bytes=250_000` default; shortens `final_prompt` and `response` (longest-first, proportionally) until the serialized trace fits
    - Set `truncated=True` only when content was actually removed; all other fields untouched
    - _Requirements: 3.8_

  - [x] 2.4 Write property test for truncation
    - **Property 12: Truncation fits, flags, and preserves**
    - **Validates: Requirements 3.8**

  - [x] 2.5 Implement `TraceSink` protocol and `CloudWatchTraceSink` in `sink.py`
    - `emit(trace)` prints exactly one JSON line with `log_type: "trace"` and all trace fields, `ensure_ascii=False` for Arabic text
    - _Requirements: 3.1_

  - [x] 2.6 Write property test for trace emission round trip
    - **Property 8: Trace emission round trip**
    - **Validates: Requirements 3.1**

  - [x] 2.7 Implement `TraceRepository` protocol, `DynamoTraceRepository`, and `TraceStoreError` in `repository.py`
    - `put(trace)`: PutItem to `TRACE_TABLE` keyed by `RequestId` with `ExpiresAt = now + retention_days` TTL; raises `TraceStoreError` on failure
    - `get(request_id)`: GetItem returning `Trace | None` — `None` for not-found, distinguishable from raised `TraceStoreError` on transport/permission failure
    - _Requirements: 3.2, 3.4, 3.6, 3.9_

  - [x] 2.8 Write property test for trace store round trip
    - **Property 9: Trace store round trip and not-found distinction**
    - **Validates: Requirements 3.4, 3.9, 12.1**

- [x] 3. Trace finalizer and composition root
  - [x] 3.1 Implement `TraceFinalizer` orchestrator in `finalizer.py`
    - Constructor-injected `estimator`, `truncator`, `sink`, `repository`, `enabled` flag
    - `finalize(ctx)`: no-op when disabled; otherwise build → estimate cost → truncate → emit → persist (persist only when ctx has no failure)
    - Catch persistence errors, log `{"log_type": "trace_persist_error", "request_id": ...}`, never propagate to the response path; any other internal exception degrades to a logged warning
    - _Requirements: 3.1, 3.3, 3.5, 3.7_

  - [x] 3.2 Write property test for persistence failure isolation
    - **Property 10: Persistence failures never disturb the response**
    - **Validates: Requirements 3.5**

  - [x] 3.3 Write property test for disabled tracing
    - **Property 11: Disabled tracing preserves Request_ID behavior**
    - **Validates: Requirements 3.7**

  - [x] 3.4 Implement `wiring.py` composition root
    - `build_trace_finalizer()` (lru_cache): reads `TRACE_TABLE`, `TRACE_ENABLED`, `TRACE_RETENTION_DAYS`, `MODEL_PRICING`; constructs the production object graph
    - `build_trace_repository()` shared by wiring and triage tooling
    - _Requirements: 3.6, 3.7_

- [x] 4. Pipeline integration touchpoints
  - [x] 4.1 Update `backend/src/streaming/agent_events.py` event contracts
    - Add `AgentEvent.meta(request_id)` factory; add `request_id` parameter to `done` and `error` factories
    - _Requirements: 1.3, 1.5_

  - [x] 4.2 Implement `AgentEventRecorder` in `observability/instrumentation.py` and hook into `chains/conversation.py`
    - Recorder maps LangGraph events to context recordings: `on_chat_model_start` → `record_prompt` (last wins), first `on_chat_model_stream` text chunk → `mark_first_token`, `on_chat_model_end` → `record_usage` from `usage_metadata` (absent ⇒ counts stay `None`), `on_complete` → `record_response`; track `current_step` via `on_tool_start`/`on_tool_end`
    - `conversation.py` adds exactly two calls: `recorder.on_event(event)` in the existing loop and `recorder.on_complete(answer)` after it
    - _Requirements: 1.2, 2.3, 2.4, 2.6, 2.8_

  - [x] 4.3 Add retrieval recording hook to `services/retrieval_service.py`
    - 3-line addition at end of `retrieve()`: capture latency via `time.monotonic()`, call `ctx.record_retrieval(chunks, latency_ms)` when a context is current
    - _Requirements: 1.2, 2.2_

  - [x] 4.4 Wire trace lifecycle into `app.py` `/api/ask`
    - Create `TraceContext` before any pipeline step; set/reset the ContextVar around the stream
    - Yield `meta` event with `request_id` first; `mark_first_token` on first token; `done` event repeats `request_id`
    - On mid-stream exception: `record_failure` + `error` event carrying `request_id`; on pre-stream failure: `record_failure`, emit-only finalize, HTTP 500 detail includes `request_id`
    - `finalizer.finalize(ctx)` in `finally` — after the last token, before the generator returns
    - _Requirements: 1.1, 1.3, 1.5, 2.1, 3.2, 3.7_

  - [x] 4.5 Write property test for Request_ID uniqueness and propagation
    - **Property 1: Request_ID uniqueness and universal propagation**
    - **Validates: Requirements 1.1, 1.2, 1.4**

  - [x] 4.6 Write property test for Request_ID stream delivery
    - **Property 2: Request_ID reaches the client before the stream ends**
    - **Validates: Requirements 1.3**

  - [x] 4.7 Write property test for failure traces
    - **Property 7: Failure traces are partial, attributed, emitted, and never persisted**
    - **Validates: Requirements 1.5, 2.6, 2.10, 3.3**

  - [x] 4.8 Write unit tests for persistence ordering and retention
    - Trace persisted before the stream generator completes (in-memory `TraceRepository`)
    - `ExpiresAt = now + retention_days` and the 90-day default
    - _Requirements: 3.2, 3.6_

- [x] 5. Trace and feedback table infrastructure (CDK)
  - [x] 5.1 Add DynamoDB tables to `infra/lib/data-stack.ts` and constants to `infra/lib/config.ts`
    - `TracesTable`: PK `RequestId` (S), TTL attribute `ExpiresAt`, PAY_PER_REQUEST
    - `FeedbackTable`: PK `RequestId` (S), GSI `RatingIndex` (PK `Rating` S, SK `FeedbackAt` S), PAY_PER_REQUEST
    - `config.ts`: `TRACE_TABLE_NAME`, `FEEDBACK_TABLE_NAME`, `TRACE_RETENTION_DAYS = 90`, `ERROR_RATE_THRESHOLD_PCT = 5`, `ERROR_RATE_PERIOD_MINUTES = 5`
    - _Requirements: 3.6, 10.6, 11.3_

  - [x] 5.2 Update `infra/lib/api-stack.ts` for tracing
    - Grant Lambda read/write on both new tables; add env vars `TRACE_TABLE`, `FEEDBACK_TABLE`, `TRACE_ENABLED`, `TRACE_RETENTION_DAYS`
    - Expose `apiLogGroup` as a public property for the observability stack
    - _Requirements: 3.6, 3.7, 10.6_

  - [x] 5.3 Write CDK assertion tests for the new tables
    - Traces and feedback tables exist with correct keys, GSI, TTL attribute, PAY_PER_REQUEST billing
    - _Requirements: 3.6, 10.6_

- [x] 6. Checkpoint - Trace logging layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Golden dataset
  - [x] 7.1 Implement `DatasetLoader` in `backend/evals/dataset.py`
    - Create `backend/evals/` package skeleton (`__init__.py`) and `backend/tests/evals/` test directory
    - `load(path) -> GoldenDataset`: per-line JSON parsing, required-field/type checks, `language ∈ {ar, en}`, category enum, Source_ID grammar (`^Quran \d+:\d+$`, `^Sahih (al-Bukhari|Muslim) \d+$`), category-consistent expected ID lists, cross-lingual counterpart existence/language/ID-set checks, ID uniqueness, dataset-level counts (50–100 total, ≥20 per language, ≥5 per category)
    - Any failure raises `DatasetValidationError` carrying `[(line_number, check_name, message), ...]` and rejects the whole file
    - Effective version `"{meta.version}+{sha256(jsonl_bytes)[:12]}"` from `golden_dataset.meta.json` + content hash; missing/unreadable file ⇒ version undeterminable error
    - _Requirements: 4.10, 4.11, 5.1, 5.2, 5.4_

  - [x] 7.2 Write property test for dataset JSONL round trip
    - **Property 13: Golden dataset JSONL round trip**
    - **Validates: Requirements 4.1, 4.5**

  - [x] 7.3 Write property test for dataset validation
    - **Property 14: Dataset validation accepts the valid and rejects the invalid with location**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11**

  - [x] 7.4 Write property test for version identifier sensitivity
    - **Property 15: Version identifier sensitivity**
    - **Validates: Requirements 5.1, 12.4**

  - [x] 7.5 Author `backend/evals/data/golden_dataset.jsonl` and `golden_dataset.meta.json`
    - 50–100 human-annotated Golden_Items: ≥20 Arabic, ≥20 English, ≥5 each of direct_lookup, paraphrase, cross_lingual, out_of_corpus
    - Cross-lingual pairs reference each other by `counterpart_id` with identical expected Source_ID sets; out_of_corpus items have empty `expected_source_ids`
    - Expected Source_IDs use the corpus citation grammar exactly; manifest starts at `{"version": "1.0.0"}`; both files committed to git
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.5_

  - [x] 7.6 Write unit test that the shipped dataset passes validation
    - Load the real `golden_dataset.jsonl` through `DatasetLoader` — proves count constraints on actual data
    - _Requirements: 4.2, 4.3, 4.6_

- [x] 8. Eval harness core
  - [x] 8.1 Implement `EvalConfig` loading and validation in `backend/evals/eval_config.py`
    - Frozen dataclass: `model_id`, `retrieval_top_k`, `prompt_version`, `judge_model_id`, `dataset_path`, `results_dir`
    - `load_config(path)`: validate presence and type of every required field, abort naming the offending parameter before any item runs
    - `model_family(model_id)`: extract vendor token from Bedrock model ID (handles regional prefixes like `us.`); judge family == generation family ⇒ abort naming the conflict
    - Add `PROMPT_VERSIONS: dict[str, str] = {"v1": AGENT_SYSTEM_PROMPT}` registry to `backend/src/prompts/islamic_qa.py`; add example `backend/evals/config.yaml`
    - _Requirements: 6.2, 6.8, 8.5, 8.8_

  - [x] 8.2 Write property test for config validation
    - **Property 18: Config validation aborts before execution**
    - **Validates: Requirements 6.2, 6.8, 8.5, 8.8**

  - [x] 8.3 Implement pipeline client protocols and production adapters in `backend/evals/pipeline.py`
    - `RetrievalClient` and `GenerationClient` protocols
    - `SrcRetrievalClient` delegates to `src.services.retrieval_service.RetrievalService`, maps chunks to `(citation, score)` pairs
    - `SrcGenerationClient`: one-shot `ChatBedrockConverse` call with `PROMPT_VERSIONS[prompt_version]` and `ContextBuilder`-formatted context — no memory, no session
    - _Requirements: 6.1, 6.6_

  - [x] 8.4 Implement `EvalRunner` in `backend/evals/runner.py`
    - `run(config, dataset)`: execute every item independently (fresh state per item), compute metrics, build and persist report
    - `_execute_item`: retrieval exception ⇒ failed(step="retrieval"); retrieval-recording failure ⇒ skip generation, item failed; generation exception ⇒ failed(step="generation") with retrieval results retained; run continues past failures
    - Per-item result records item ID, retrieved Source_IDs with scores, and generated answer together
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.7_

  - [x] 8.5 Write property test for runner independence and fidelity
    - **Property 16: Runner executes every item independently and records results faithfully**
    - **Validates: Requirements 6.1, 6.3**

  - [x] 8.6 Write property test for item failure isolation
    - **Property 17: Item failures are isolated and attributed**
    - **Validates: Requirements 6.4, 6.5**

- [x] 9. Retrieval metrics
  - [x] 9.1 Implement pure retrieval metrics in `backend/evals/metrics/retrieval.py`
    - `dedupe_ranked` (keep first/highest-rank occurrence), `recall_at_k`, `precision_at_k` (divide by k even when fewer retrieved), `mrr` (0 when no expected hit)
    - Exact string equality only; no I/O, no LLM
    - `aggregate`: arithmetic mean over applicable items (non-empty expected, not failed) — overall, by category, by language; inapplicable items marked not-computed and excluded
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 9.2 Write property test for metric definitional correctness
    - **Property 19: Retrieval metric definitional correctness**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 9.3 Write property test for matching invariants
    - **Property 20: Retrieval metric matching invariants**
    - **Validates: Requirements 7.5, 7.7**

  - [x] 9.4 Write property test for aggregation over applicable items
    - **Property 21: Retrieval aggregation over applicable items only**
    - **Validates: Requirements 7.4, 7.6, 7.8**

- [x] 10. Generation metrics (LLM-as-judge)
  - [x] 10.1 Implement `Judge` protocol and `NovaJudge` in `backend/evals/judge.py`
    - One Bedrock Converse call per (item, rubric) with `temperature=0`; prompt ends with the JSON-verdict instruction
    - `parse_verdict(text)`: extract and validate `{"verdict": "pass"|"fail", "rationale": ...}` tolerating surrounding prose; unparseable ⇒ raises
    - Rubric prompts: faithfulness, citation accuracy (zero citations ⇒ fail; judge receives retrieved chunks with Source_IDs), answer relevancy, abstention
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 10.2 Implement `GenerationScorer` in `backend/evals/metrics/generation.py`
    - `score_item`: out_of_corpus ⇒ single abstention rubric; otherwise faithfulness + citation accuracy + answer relevancy
    - Retry discipline: exactly one retry per failed/unparseable scoring call; second failure ⇒ `error` verdict distinct from pass/fail; continue remaining rubrics and items
    - Failed items never sent to the judge; their generation metrics not-computed and excluded from aggregates
    - `aggregate`: pass rate = pass / (pass + fail) with errors excluded from both numerator and denominator, plus per-metric error counts — overall, by category, by language
    - _Requirements: 8.4, 8.6, 8.7, 8.9_

  - [x] 10.3 Write property test for rubric selection
    - **Property 22: Rubric selection by category**
    - **Validates: Requirements 8.4**

  - [x] 10.4 Write property test for judge retry discipline
    - **Property 23: Judge retry discipline**
    - **Validates: Requirements 8.6**

  - [x] 10.5 Write property test for failed-item exclusion
    - **Property 24: Failed items never reach the judge**
    - **Validates: Requirements 8.9**

  - [x] 10.6 Write property test for pass-rate aggregation
    - **Property 25: Generation pass-rate aggregation**
    - **Validates: Requirements 8.7**

  - [x] 10.7 Write unit tests for verdict parsing
    - Realistic Nova outputs (JSON with surrounding prose)
    - _Requirements: 8.6_

- [x] 11. Reports, comparison, and CLI
  - [x] 11.1 Implement `EvalReport` model and `ReportRepository` in `backend/evals/report.py`
    - `run_id = "{UTC:%Y%m%dT%H%M%SZ}-{uuid4hex[:8]}"`; `persist(report)` writes `results/{run_id}/report.json`, refuses to overwrite (regenerate run id on collision), never mutates or deletes prior reports
    - `load(run_id)` reads back or raises a not-found error naming the id
    - Report JSON: run_id, config, dataset_version, completed_at, aggregates (retrieval + generation, overall/category/language), per_item (verdicts with judge rationales, or failure record), succeeded/failed counts
    - _Requirements: 5.3, 6.7, 9.1, 9.2_

  - [x] 11.2 Write property test for report persistence
    - **Property 26: Report persistence is unique and append-only**
    - **Validates: Requirements 9.1**

  - [x] 11.3 Write property test for report round trip
    - **Property 27: Report round trip**
    - **Validates: Requirements 5.3, 6.7, 9.2**

  - [x] 11.4 Implement `compare()` in `backend/evals/compare.py`
    - Pure function over two loaded reports: per-aggregate-metric `(value_a, value_b, diff)`; items whose verdicts differ listed with both verdicts
    - Different dataset versions ⇒ flag mismatch and restrict per-item comparison to the intersection of item ids
    - Unknown run id ⇒ error naming which id, no comparison output
    - _Requirements: 9.3, 9.4, 9.5, 9.6_

  - [x] 11.5 Write property test for comparison
    - **Property 28: Comparison correctness**
    - **Validates: Requirements 9.3, 9.4, 9.5, 9.6**

  - [x] 11.6 Implement `backend/evals/cli.py` and `__main__.py` composition root
    - `python -m evals run --config ...`: load/validate config (abort on invalid), load dataset via `DatasetLoader` (abort on invalid or undeterminable version, before executing any item), construct `EvalRunner(SrcRetrievalClient, SrcGenerationClient, GenerationScorer(NovaJudge), ReportRepository)` and run
    - `python -m evals compare <run_a> <run_b>`: load both reports, print comparison
    - Runnable from `backend/` on a developer machine with AWS credentials against deployed resources
    - _Requirements: 4.11, 5.2, 5.4, 6.6, 6.8, 8.8_

  - [x] 11.7 Write unit test for version-before-execution ordering
    - Dataset version resolved before first item execution (mocked runner)
    - _Requirements: 5.2_

- [x] 12. Checkpoint - Eval harness complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Observability infrastructure (CDK)
  - [x] 13.1 Implement `infra/lib/observability-stack.ts` and instantiate it in the CDK app entry
    - Metric filters on the API log group (namespace `NoorAi/Traces`): `RequestCount`, `ErrorCount`, `ThrottleCount` with the trace-field patterns
    - Dashboard: Logs Insights widgets for latency percentiles (p50/p90/p99), TTFT percentiles, daily cost sum by UTC day; metric widgets for error rate (`MathExpression("100 * errors / requests")`) and throttle counts
    - Alarm: error-rate metric math, threshold 5%, period 5 min, `GREATER_THAN_THRESHOLD`, `treatMissingData: NOT_BREACHING`; optional SNS topic + email subscription when `ALARM_EMAIL` configured
    - Wire `apiLogGroup` from `ApiStack` via `ObservabilityStackProps`; instantiate in the bin entry
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

  - [x] 13.2 Write CDK assertion tests in `infra/test/observability-stack.test.ts`
    - Three metric filters with expected patterns; dashboard body contains latency, TTFT, error-rate, throttling, and daily-cost widgets
    - Alarm assertions: metric-math expression, threshold 5, 5-minute period, `TreatMissingData: notBreaching`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

- [x] 14. Feedback API (backend)
  - [x] 14.1 Implement `backend/src/feedback/` package
    - `models.py`: `FeedbackRequest` (`request_id` min_length=1, `rating: Literal["up","down"]`, optional `comment` ≤2000) and `FeedbackRecord`
    - `repository.py`: `FeedbackRepository` protocol + `DynamoFeedbackRepository` — PutItem to `FEEDBACK_TABLE` (unconditional overwrite), `list_down_rated()` querying `RatingIndex` newest-first
    - `service.py`: `FeedbackService.submit` builds `{RequestId, Rating, Comment?, FeedbackAt: iso-utc}` and stores it
    - `router.py`: `POST /api/feedback` returning 204, service via `Depends(build_feedback_service)`; Pydantic 422 on invalid body with nothing persisted
    - Include the router in `app.py` with one line
    - _Requirements: 11.2, 11.3, 11.4, 11.5_

  - [x] 14.2 Write property test for feedback persistence
    - **Property 29: Feedback persistence is validated last-write-wins**
    - **Validates: Requirements 11.3, 11.4, 11.5**

- [x] 15. Feedback UI (frontend)
  - [x] 15.1 Extend stream types and API client in `frontend/lib/api.ts` and `frontend/lib/types.ts`
    - `AgentStreamEvent` gains `{ type: "meta"; request_id: string }`; `request_id` added to `done`/`error`
    - `submitFeedback(requestId, rating): Promise<void>` with 10 s `AbortSignal.timeout`
    - `Message` gains `requestId?: string` and `feedback?: "up" | "down" | "error"`
    - _Requirements: 11.2, 11.7_

  - [x] 15.2 Implement `frontend/components/FeedbackControls.tsx` and wire into chat components
    - Thumbs up/down controls; on click → `submitFeedback`; success → brief confirmation state then controls hidden; error/timeout → "not saved" indicator with controls kept for retry, chat unaffected
    - `ChatWindow.tsx`: stamp `requestId` from `meta`/`done` events onto the in-flight assistant message; persist `requestId` in the localStorage chatStore
    - `MessageBubble.tsx`: render `<FeedbackControls>` only when `!stream && requestId`; no controls when no Request_ID was received
    - _Requirements: 11.1, 11.2, 11.6, 11.7, 11.8_

- [x] 16. Triage path
  - [x] 16.1 Implement `TriageService` in `backend/evals/triage.py` and add triage commands to `cli.py`
    - `TriageService(feedback, traces, dataset)` reusing `DynamoFeedbackRepository` and `DynamoTraceRepository` — no duplicate data-access code
    - `list_down_rated()`: down-rated records newest-first, each with Request_ID, timestamp, and query/response from the linked Trace, or a trace-unavailable indication when no Trace exists
    - `draft(request_id)`: trace unavailable ⇒ error, no draft; otherwise emit a schema-conformant JSONL draft with unique id (`triage-{n}`), question and detected language (Arabic-script codepoint ratio) from the Trace, and `category: "TODO"`, `expected_source_ids: []`, `reference_answer: null` left for annotation
    - CLI: `python -m evals triage list` and `python -m evals triage draft <request_id>` wired with the production repositories
    - _Requirements: 12.1, 12.2, 12.3, 12.5, 12.6_

  - [x] 16.2 Write property test for triage listing
    - **Property 30: Triage listing completeness and order**
    - **Validates: Requirements 12.2, 12.5**

  - [x] 16.3 Write property test for draft generation
    - **Property 31: Draft Golden_Item generation**
    - **Validates: Requirements 12.3, 12.6**

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP; they map one-to-one to the design's correctness properties (Hypothesis, ≥100 examples, in-memory fakes, no AWS calls)
- Layer order is deliberate: trace logging (tasks 1–6) → golden dataset (7) → eval harness (8–12) → online metrics and feedback (13–17), since each layer depends on the previous
- Frontend feedback UI behavior (Req 11.1, 11.6, 11.7, 11.8) has no test runner today and is verified manually; the feedback API contract is fully property-tested on the backend (Property 29)
- Live-AWS smoke checks (end-to-end eval run, post-deploy trace verification, alarm state) are manual per the design's testing strategy and are not coding tasks
- Each task references specific granular requirements for traceability

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.3", "2.5", "5.1", "7.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "1.5", "2.1", "2.4", "2.6", "2.7", "5.2", "7.2", "7.3", "7.4", "7.5", "8.1"] },
    { "id": 3, "tasks": ["2.2", "2.8", "3.1", "4.1", "5.3", "7.6", "8.2", "8.3", "9.1", "10.1", "13.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "3.4", "4.2", "9.2", "9.3", "9.4", "10.2", "13.2", "14.1"] },
    { "id": 5, "tasks": ["4.3", "8.4", "10.3", "10.4", "10.5", "10.6", "10.7", "11.1", "14.2", "15.1"] },
    { "id": 6, "tasks": ["4.4", "8.5", "8.6", "11.2", "11.3", "11.4", "15.2", "16.1"] },
    { "id": 7, "tasks": ["4.5", "4.6", "4.7", "4.8", "11.5", "11.6", "16.2", "16.3"] },
    { "id": 8, "tasks": ["11.7"] }
  ]
}
```
