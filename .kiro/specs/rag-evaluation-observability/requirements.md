# Requirements Document

## Introduction

Noor-AI is a deployed bilingual (Arabic/English) Islamic Q&A RAG application answering questions from the Quran, Sahih Bukhari, and Sahih Muslim. Today it has no structured logging, no evaluation dataset, no offline eval harness, and no user feedback loop — quality changes are invisible and regressions are undetectable.

This feature adds an evaluation and observability system in four parts, built in order because each layer depends on the previous one:

1. **Trace logging** — a structured, per-request trace (query, retrieved chunks, prompt, response, timings, tokens, cost) identified by a request ID, emitted to CloudWatch and persisted for later reference.
2. **Golden dataset** — a versioned, human-annotated evaluation dataset of Arabic and English questions labeled with expected source IDs, including out-of-corpus questions where the correct behavior is abstaining.
3. **Offline eval harness** — a config-driven runner that executes the golden dataset through the pipeline and produces versioned reports with code-based retrieval metrics (recall@k, precision@k, MRR) and LLM-as-judge generation metrics (faithfulness, citation accuracy, answer relevancy).
4. **Online metrics and feedback** — a CloudWatch dashboard and alarm built from the structured traces, plus a thumbs up/down feedback loop linked to traces by request ID, with a path from bad production queries into new golden dataset rows.

The system follows a two-dimensional evaluation framework: scope (component-level retriever and LLM evals vs. system-level evals) crossed with evaluator type (code-based, LLM-as-judge, human feedback). This is a single-developer portfolio project, so serverless, low-cost solutions are preferred.

## Glossary

- **Noor_AI_Pipeline**: The existing deployed RAG request path — FastAPI on Lambda (Web Adapter, streaming Function URL), LangGraph agent, Bedrock Knowledge Base retrieval, Claude Haiku 4.5 generation, DynamoDB chat memory.
- **Trace_Logger**: The new backend component that assembles and emits one structured trace per chat request.
- **Trace**: A structured JSON record of a single chat request, containing the request ID, query, retrieval results, final prompt, response, per-step timings, token counts, and cost estimate.
- **Request_ID**: A unique identifier generated once per chat request and propagated through every pipeline step, trace record, log line, and feedback record.
- **Trace_Store**: The persistent store (DynamoDB table or S3 prefix) holding Traces keyed by Request_ID so offline evals and feedback can reference them.
- **Source_ID**: The unambiguous identifier of a corpus document — a Quran verse reference (surah:ayah) or a hadith reference (collection + hadith number) — derivable from the one-item-per-file corpus layout.
- **Golden_Dataset**: The versioned, human-annotated evaluation dataset of questions labeled with expected Source_IDs and optional reference answers.
- **Golden_Item**: A single row of the Golden_Dataset: question text, language, category, expected Source_IDs (empty for out-of-corpus items), and optional reference answer.
- **Abstention**: The behavior of declining to answer with a clear "no source found" response instead of generating unsupported content.
- **Eval_Harness**: The offline evaluation runner in backend/evals/ that executes Golden_Items through retrieval and generation and computes metrics.
- **Eval_Config**: The set of parameters controlling an Eval_Harness run — at minimum model ID, retrieval top-k, and prompt version.
- **Eval_Report**: The versioned output of one Eval_Harness run: aggregate metrics plus per-item results, annotated with the Eval_Config, Golden_Dataset version, and timestamp used to produce it.
- **Judge_Model**: The LLM used for LLM-as-judge generation metrics; a model from a different family than the generation model (e.g., Amazon Nova) to avoid self-preference bias.
- **Retrieval_Metrics**: Deterministic code-based metrics comparing retrieved Source_IDs to expected Source_IDs: recall@k, precision@k, MRR.
- **Generation_Metrics**: LLM-as-judge metrics on generated answers: faithfulness, citation accuracy, answer relevancy, each scored with a discrete pass/fail rubric.
- **Ops_Dashboard**: The CloudWatch dashboard built from structured trace logs showing latency, TTFT, error rate, throttling, and cost.
- **TTFT**: Time to first token — elapsed time from request receipt to the first streamed response token.
- **Feedback_API**: The new backend endpoint accepting thumbs up/down feedback for a completed chat response.
- **Feedback_Record**: A stored feedback entry containing the Request_ID, rating (up/down), optional comment, and timestamp.
- **Feedback_UI**: The thumbs up/down controls in the Next.js frontend attached to each assistant response.
- **Triage_Path**: The documented workflow and tooling for converting a negatively-rated production query (via its Trace) into a new Golden_Item.

## Requirements

### Requirement 1: Request ID Propagation

**User Story:** As a developer, I want every chat request assigned a unique request ID that flows through the entire pipeline, so that logs, traces, and feedback for one request can be correlated.

#### Acceptance Criteria

1. WHEN a chat request is received, THE Noor_AI_Pipeline SHALL generate a Request_ID that is unique across all chat requests before any pipeline step executes.
2. WHILE processing a single chat request, THE Noor_AI_Pipeline SHALL propagate the identical Request_ID value to the retrieval step, the generation step, the streaming layer, and the Trace_Logger, such that the Trace and all log lines emitted for that request carry the same Request_ID value.
3. WHEN a chat response is streamed to the client, THE Noor_AI_Pipeline SHALL include the Request_ID in the response stream such that the client has received the Request_ID by the time the final response token is delivered.
4. WHEN any structured log line is emitted during a chat request, THE Trace_Logger SHALL include the Request_ID in that log line.
5. IF a chat request fails after the Request_ID has been generated, THEN THE Noor_AI_Pipeline SHALL include the Request_ID in the error response returned to the client.

### Requirement 2: Structured Trace Capture

**User Story:** As a developer, I want a structured JSON trace of every chat request capturing inputs, retrieval results, outputs, timings, and cost, so that I can debug individual requests and compute aggregate metrics.

#### Acceptance Criteria

1. WHEN a chat request completes, whether successfully or with an error, THE Trace_Logger SHALL assemble a Trace containing the Request_ID, the user query text, the conversation/session identifier, and the request receipt timestamp in UTC.
2. WHEN the retrieval step completes, THE Trace_Logger SHALL record in the Trace the ordered list of retrieved chunk Source_IDs, the relevance score of each retrieved chunk, and the retrieval latency in milliseconds, recording an empty list when zero chunks are retrieved.
3. WHEN the generation step completes, THE Trace_Logger SHALL record in the Trace the final prompt sent to the model, the complete model response assembled from all streamed tokens, the input token count, and the output token count.
4. WHEN a chat request completes, THE Trace_Logger SHALL record in the Trace the TTFT in milliseconds and the total request latency in milliseconds, where total request latency is measured from request receipt to the last streamed response token.
5. WHEN a chat request completes, THE Trace_Logger SHALL record in the Trace an estimated cost in USD computed from the recorded input and output token counts and the configured per-token pricing for the model used in that request.
6. IF a pipeline step fails, THEN THE Trace_Logger SHALL record in the Trace the failing step name and the error message, SHALL retain all Trace fields captured before the failure, and SHALL still emit the partial Trace to CloudWatch Logs.
7. THE Trace_Logger SHALL identify each Trace with a trace schema version field.
8. IF the input token count or output token count is unavailable when a chat request completes, THEN THE Trace_Logger SHALL record the missing token count as unavailable and SHALL mark the cost estimate as not computed rather than recording a zero or substituted value.
9. IF no per-token pricing is configured for the model used in a request, THEN THE Trace_Logger SHALL mark the cost estimate in the Trace as not computed and SHALL still assemble and emit the Trace.
10. IF a chat request fails before the first response token is streamed, THEN THE Trace_Logger SHALL mark the TTFT in the Trace as not recorded.

### Requirement 3: Trace Emission and Persistence

**User Story:** As a developer, I want traces emitted to CloudWatch as structured JSON and persisted in a queryable store, so that dashboards can aggregate them and evals and feedback can look them up by request ID.

#### Acceptance Criteria

1. WHEN a Trace is assembled, THE Trace_Logger SHALL emit the Trace to CloudWatch Logs as a single structured JSON log entry.
2. WHEN a chat request is processed successfully, THE Trace_Logger SHALL persist the Trace to the Trace_Store keyed by Request_ID before the request invocation completes, so the Trace is retrievable by Request_ID immediately after the response is delivered.
3. IF a chat request fails, THEN THE Trace_Logger SHALL emit the partial Trace to CloudWatch Logs only and SHALL NOT persist the partial Trace to the Trace_Store.
4. WHEN a Trace is requested from the Trace_Store by an existing Request_ID, THE Trace_Store SHALL return the complete Trace as it was persisted for that Request_ID.
5. IF persisting a Trace to the Trace_Store fails, THEN THE Trace_Logger SHALL log a persistence error that includes the Request_ID, SHALL NOT surface any error indication to the user, and SHALL complete the chat response to the user without interruption.
6. THE Trace_Store SHALL apply a configurable retention period to persisted Traces, with a default of 90 days, after which expired Traces are no longer retrievable by Request_ID.
7. WHERE trace logging is disabled via configuration, THE Noor_AI_Pipeline SHALL process chat requests without emitting or persisting Traces, and SHALL continue to generate and propagate the Request_ID per Requirement 1 so feedback submission remains functional.
8. IF an assembled Trace exceeds the maximum size of a single CloudWatch Logs entry, THEN THE Trace_Logger SHALL truncate the final prompt and model response fields until the Trace fits within one entry, SHALL mark the Trace with a truncation indicator, and SHALL still emit and persist the truncated Trace.
9. IF no Trace exists in the Trace_Store for a requested Request_ID, THEN THE Trace_Store SHALL return a not-found result that is distinguishable from a retrieval error.

### Requirement 4: Golden Dataset Content and Format

**User Story:** As a developer, I want a human-annotated evaluation dataset in a defined file format with labeled expected sources, so that retrieval and generation quality can be measured deterministically.

#### Acceptance Criteria

1. THE Golden_Dataset SHALL store Golden_Items in a UTF-8 encoded JSONL file format where each line is exactly one Golden_Item as a single JSON object.
2. THE Golden_Dataset SHALL contain between 50 and 100 Golden_Items.
3. THE Golden_Dataset SHALL contain at least 20 Golden_Items whose question language is Arabic and at least 20 Golden_Items whose question language is English.
4. Each Golden_Item SHALL contain an item ID that is unique across the Golden_Dataset, a non-empty question text, a question language whose value is either Arabic or English, a category label whose value is one of direct lookup, paraphrase, cross-lingual, or out-of-corpus, and a list of expected Source_IDs.
5. WHERE a reference answer has been authored for a Golden_Item, THE Golden_Dataset SHALL store the reference answer on that Golden_Item.
6. THE Golden_Dataset SHALL include at least 5 Golden_Items in each of these categories: direct lookup, paraphrase, cross-lingual, and out-of-corpus.
7. Each cross-lingual Golden_Item SHALL reference, by item ID, a counterpart Golden_Item that exists in the same Golden_Dataset, is in the other language, and shares the same expected Source_IDs.
8. Each out-of-corpus Golden_Item SHALL have an empty expected Source_ID list, and the expected behavior for that item SHALL be Abstention.
9. Each Golden_Item in the direct lookup, paraphrase, or cross-lingual category SHALL contain at least one expected Source_ID, and each expected Source_ID SHALL conform to the Source_ID format defined in the Glossary.
10. WHEN a Golden_Dataset file is loaded, THE Eval_Harness SHALL validate every Golden_Item for required field presence, item ID uniqueness, allowed language and category values, expected Source_ID format, category-consistent expected Source_ID lists per criteria 8 and 9, and existence of referenced cross-lingual counterparts.
11. IF any Golden_Item fails validation during loading, THEN THE Eval_Harness SHALL reject the entire Golden_Dataset file without executing any Golden_Items and SHALL report, for each invalid line, the line number and the validation check that failed.

### Requirement 5: Golden Dataset Versioning

**User Story:** As a developer, I want the golden dataset versioned, so that eval reports are reproducible and comparable against a known dataset state.

#### Acceptance Criteria

1. THE Golden_Dataset SHALL carry an explicit version identifier, stored with the Golden_Dataset in the project repository, such that any two Golden_Dataset states that differ in the set or content of Golden_Items have different version identifiers.
2. WHEN an Eval_Harness run starts, THE Eval_Harness SHALL determine the Golden_Dataset version identifier before executing any Golden_Item.
3. WHEN an Eval_Harness run completes, THE Eval_Harness SHALL record in the Eval_Report the Golden_Dataset version identifier determined at the start of that run.
4. IF the Golden_Dataset version identifier cannot be determined, THEN THE Eval_Harness SHALL abort the run with an error message indicating that the version identifier could not be determined, SHALL NOT execute any Golden_Item, and SHALL NOT produce an Eval_Report.
5. THE Golden_Dataset SHALL be stored in the project repository so that every change to Golden_Items is recorded in source control history.

### Requirement 6: Eval Harness Execution

**User Story:** As a developer, I want a config-driven offline eval harness that runs the golden dataset through the pipeline, so that I can measure quality and compare configuration changes.

#### Acceptance Criteria

1. WHEN the Eval_Harness is invoked with an Eval_Config and a Golden_Dataset, THE Eval_Harness SHALL execute every Golden_Item through the retrieval step and the generation step of the Noor_AI_Pipeline, executing each Golden_Item independently so that no conversation memory or state from one Golden_Item affects the execution of another.
2. THE Eval_Harness SHALL accept the model ID, the retrieval top-k, and the prompt version as Eval_Config inputs.
3. WHEN executing a Golden_Item, THE Eval_Harness SHALL record the Golden_Item ID, the retrieved Source_IDs with scores, and the generated answer for that item together as one per-item result.
4. IF recording the retrieved Source_IDs for a Golden_Item fails, THEN THE Eval_Harness SHALL skip recording the generated answer for that item and SHALL record the item as failed.
5. IF execution of a single Golden_Item fails, THEN THE Eval_Harness SHALL record for that item a failure result containing the failing step (retrieval or generation) and an error description, and SHALL continue executing the remaining Golden_Items.
6. THE Eval_Harness SHALL reside in the backend/evals/ directory and SHALL be runnable from a developer machine against deployed AWS resources.
7. WHEN an Eval_Harness run completes, THE Eval_Harness SHALL write an Eval_Report containing the Eval_Config used, the Golden_Dataset version, a run timestamp, aggregate metrics, per-item results including failed items marked as failed, and the counts of succeeded and failed Golden_Items.
8. IF the Eval_Config is missing any required parameter (model ID, retrieval top-k, or prompt version) or contains a value of the wrong type, THEN THE Eval_Harness SHALL abort the run with an error message identifying the invalid parameter before executing any Golden_Item.

### Requirement 7: Retrieval Metrics

**User Story:** As a developer, I want deterministic code-based retrieval metrics computed against labeled source IDs, so that retriever quality is measured objectively and regressions are detectable.

#### Acceptance Criteria

1. WHEN an Eval_Harness run completes retrieval for the Golden_Items, THE Eval_Harness SHALL compute recall@k for each Golden_Item that has expected Source_IDs, using the configured top-k, where recall@k is the count of expected Source_IDs present in the top-k retrieved results divided by the total count of expected Source_IDs for that item.
2. WHEN an Eval_Harness run completes retrieval for the Golden_Items, THE Eval_Harness SHALL compute precision@k for each Golden_Item that has expected Source_IDs, using the configured top-k, where precision@k is the count of retrieved Source_IDs in the top-k results that appear in the expected Source_IDs divided by k, including when fewer than k results were retrieved.
3. WHEN an Eval_Harness run completes retrieval for the Golden_Items, THE Eval_Harness SHALL compute MRR for each Golden_Item that has expected Source_IDs, where the reciprocal rank for an item is 1 divided by the rank position of the highest-ranked retrieved Source_ID that appears in the expected Source_IDs, and 0 when no expected Source_ID appears in the retrieved results.
4. WHEN a Golden_Item has an empty expected Source_ID list, THE Eval_Harness SHALL mark Retrieval_Metrics for that item as not computed and SHALL exclude that item from aggregate Retrieval_Metrics.
5. THE Eval_Harness SHALL compute Retrieval_Metrics by exact string equality comparison of retrieved Source_IDs against expected Source_IDs, without partial or fuzzy matching, counting duplicate retrieved Source_IDs as a single occurrence at their highest rank, and without invoking any LLM.
6. WHEN aggregate Retrieval_Metrics are reported, THE Eval_Harness SHALL report the arithmetic mean of each metric across the applicable Golden_Items, both overall and broken down by category and by language, where applicable Golden_Items are those with a non-empty expected Source_ID list that were not recorded as failed.
7. WHEN Retrieval_Metrics computation is executed more than once on the same recorded retrieval results, THE Eval_Harness SHALL produce identical metric values on every execution.
8. IF a Golden_Item was recorded as failed during Eval_Harness execution, THEN THE Eval_Harness SHALL mark Retrieval_Metrics for that item as not computed and SHALL exclude that item from aggregate Retrieval_Metrics.

### Requirement 8: Generation Metrics (LLM-as-Judge)

**User Story:** As a developer, I want generated answers scored by an independent judge model on faithfulness, citation accuracy, and answer relevancy, so that generation quality is measured without self-preference bias.

#### Acceptance Criteria

1. WHEN an Eval_Harness run completes generation for a Golden_Item, THE Eval_Harness SHALL score the generated answer for faithfulness using the Judge_Model with a discrete pass/fail rubric, where pass requires every claim in the answer to be supported by the retrieved chunks.
2. WHEN an Eval_Harness run completes generation for a Golden_Item, THE Eval_Harness SHALL score the generated answer for citation accuracy using the Judge_Model with a discrete pass/fail rubric, where pass requires the answer to contain at least one cited Source_ID and each cited Source_ID to support the statement it is attached to, such that an answer containing zero cited Source_IDs is scored as fail.
3. WHEN an Eval_Harness run completes generation for a Golden_Item, THE Eval_Harness SHALL score the generated answer for answer relevancy using the Judge_Model with a discrete pass/fail rubric, where pass requires the answer to address the question asked.
4. WHEN an out-of-corpus Golden_Item is evaluated, THE Eval_Harness SHALL replace the faithfulness, citation accuracy, and answer relevancy rubrics for that item with a single abstention rubric, scored by the Judge_Model with a discrete pass/fail rubric, that passes only when the answer is an Abstention.
5. THE Eval_Harness SHALL accept the Judge_Model identifier as an Eval_Config input and SHALL use a Judge_Model from a different model family than the generation model configured in the same Eval_Config.
6. IF a Judge_Model scoring call fails or returns an unparseable verdict, THEN THE Eval_Harness SHALL retry that scoring call exactly once, and IF the retry also fails or returns an unparseable verdict, THEN THE Eval_Harness SHALL record that score as an evaluation error distinct from pass and fail and SHALL continue scoring the remaining metrics and Golden_Items.
7. WHEN aggregate Generation_Metrics are reported, THE Eval_Harness SHALL report the pass rate of each metric, computed as the count of pass verdicts divided by the count of pass and fail verdicts for that metric with evaluation errors excluded from both numerator and denominator, both overall and broken down by category and by language, together with the count of evaluation errors for each metric.
8. IF the Judge_Model configured in the Eval_Config is from the same model family as the generation model configured in the Eval_Config, THEN THE Eval_Harness SHALL abort the run with an error message identifying the model family conflict before scoring any Golden_Item.
9. IF a Golden_Item was recorded as failed during Eval_Harness execution, THEN THE Eval_Harness SHALL NOT invoke the Judge_Model for that item, SHALL mark Generation_Metrics for that item as not computed, and SHALL exclude that item from aggregate Generation_Metrics.

### Requirement 9: Eval Report Versioning and Comparison

**User Story:** As a developer, I want eval results stored as versioned artifacts that can be compared between runs, so that I can quantify the effect of model, prompt, or retriever changes.

#### Acceptance Criteria

1. WHEN an Eval_Harness run completes, THE Eval_Harness SHALL persist the Eval_Report to the results location under a run identifier that is unique among all persisted Eval_Reports, and SHALL NOT modify or delete any previously persisted Eval_Report.
2. THE Eval_Report SHALL be stored in a machine-readable format that includes the run identifier, the Eval_Config used for the run, the Golden_Dataset version evaluated, the run completion timestamp, aggregate metrics, and per-item results containing each Golden_Item's pass/fail verdict and the judge rationale for that verdict.
3. WHEN a comparison is requested with two run identifiers that each match a persisted Eval_Report, THE Eval_Harness SHALL produce a comparison output listing, for each aggregate metric, the metric value from each run and the numeric difference between the two values.
4. WHEN a comparison is requested with two run identifiers that each match a persisted Eval_Report, THE Eval_Harness SHALL identify each Golden_Item whose pass/fail verdict differs between the two runs, listing the Golden_Item identifier and the verdict from each run.
5. IF the two Eval_Reports being compared were produced from different Golden_Dataset versions, THEN THE Eval_Harness SHALL include in the comparison output an indication that the Golden_Dataset versions differ, and SHALL restrict per-item verdict comparison to Golden_Items present in both Eval_Reports.
6. IF a comparison is requested with a run identifier that does not match any persisted Eval_Report, THEN THE Eval_Harness SHALL return an error message indicating which run identifier was not found, and SHALL NOT produce a comparison output.

### Requirement 10: Operational Dashboard and Alarm

**User Story:** As a developer, I want a CloudWatch dashboard and alarm derived from the structured trace logs, so that I can monitor production health, latency, and cost at a glance and get notified of problems.

#### Acceptance Criteria

1. THE Ops_Dashboard SHALL display total request latency percentiles (at minimum p50, p90, p99) in milliseconds, derived from the total request latency field of structured trace logs.
2. THE Ops_Dashboard SHALL display TTFT percentiles (at minimum p50, p90, p99) in milliseconds, derived from the TTFT field of structured trace logs.
3. THE Ops_Dashboard SHALL display the request error rate, computed as the number of requests whose Trace records a pipeline step failure divided by the total number of requests in the same aggregation period, expressed as a percentage.
4. THE Ops_Dashboard SHALL display the count of Bedrock throttling errors per aggregation period, identified from the error information recorded in structured trace logs.
5. THE Ops_Dashboard SHALL display estimated cost per day, computed as the sum in USD of the per-request cost estimates in structured trace logs for each calendar day (UTC).
6. THE Ops_Dashboard, its metric definitions, and the error rate alarm SHALL be defined in the CDK infrastructure code.
7. WHEN the request error rate strictly exceeds a configured threshold percentage (default 5%) over a configured evaluation period (default 5 minutes), THE monitoring system SHALL transition the CloudWatch alarm to the ALARM state using standard CloudWatch alarm delivery.
8. IF zero requests are received during an evaluation period, THEN THE monitoring system SHALL treat the missing error rate data as not breaching and SHALL NOT transition the alarm to the ALARM state.

### Requirement 11: User Feedback Capture

**User Story:** As a user, I want to rate an answer thumbs up or thumbs down, so that the developer learns which answers are good or bad.

#### Acceptance Criteria

1. WHEN an assistant response finishes rendering and the Request_ID for that response has been received by the frontend, THE Feedback_UI SHALL display thumbs up and thumbs down controls for that response.
2. WHEN a user selects a thumbs up or thumbs down control, THE Feedback_UI SHALL submit a Feedback_Record containing the Request_ID of the rated response and a rating value of up or down to the Feedback_API.
3. WHEN the Feedback_API receives a valid Feedback_Record, THE Feedback_API SHALL persist the Feedback_Record keyed by Request_ID with the rating value and a timestamp.
4. IF the Feedback_API receives a submission that is missing a Request_ID or contains a rating value other than up or down, THEN THE Feedback_API SHALL reject the submission with a 4xx error response and SHALL NOT persist a Feedback_Record for that submission.
5. WHEN the Feedback_API receives a valid Feedback_Record for a Request_ID that already has a persisted Feedback_Record, THE Feedback_API SHALL overwrite the previously persisted rating and timestamp for that Request_ID with the new values.
6. WHEN the Feedback_UI receives a success response from the Feedback_API for a submitted rating, THE Feedback_UI SHALL display a confirmation state on the selected control and SHALL then hide the rating controls for that response.
7. IF the Feedback_API returns an error response or does not respond within 10 seconds, THEN THE Feedback_UI SHALL indicate that the rating was not saved, SHALL keep the rating controls available for the user to retry, and SHALL keep the chat conversation usable.
8. IF no Request_ID was received for an assistant response, THEN THE Feedback_UI SHALL NOT display rating controls for that response.

### Requirement 12: Feedback Triage into Golden Dataset

**User Story:** As a developer, I want to turn negatively-rated production queries into new golden dataset rows, so that the eval dataset grows from real failure cases.

#### Acceptance Criteria

1. WHEN a developer looks up a Feedback_Record, THE Trace_Store SHALL provide the complete persisted Trace keyed by the Request_ID contained in that Feedback_Record, per Requirement 3 criterion 4.
2. WHEN a developer invokes the triage listing mechanism, THE Triage_Path SHALL list the Feedback_Records whose rating value is down, ordered by feedback timestamp with the most recent first, showing for each record the Request_ID, the feedback timestamp, and the query text and model response from the linked Trace.
3. WHEN a developer selects a negatively-rated request for triage, THE Triage_Path SHALL produce a draft Golden_Item conforming to the Golden_Dataset JSONL schema defined in Requirement 4, pre-filled with an item ID unique across the existing Golden_Dataset and the query text and language from the Trace, leaving the expected Source_IDs, the category label, and the optional reference answer for human annotation.
4. WHEN a human-annotated Golden_Item produced by the Triage_Path is added to the Golden_Dataset, THE Golden_Dataset version identifier SHALL change to a value different from the pre-addition identifier, per Requirement 5.
5. IF the Trace for a negatively-rated Feedback_Record does not exist in the Trace_Store (never persisted for a failed request, or expired past the retention period), THEN THE Triage_Path SHALL still list that Feedback_Record with an indication that its Trace is unavailable.
6. IF a developer selects a Feedback_Record whose Trace is unavailable for triage, THEN THE Triage_Path SHALL report an error indicating the Trace is unavailable and SHALL NOT produce a draft Golden_Item.
