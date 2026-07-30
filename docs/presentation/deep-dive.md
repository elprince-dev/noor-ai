---
marp: true
theme: noor
paginate: true
footer: 'Noor AI · noorai.elprince.net'
title: 'Noor AI — Serverless Agentic RAG on AWS'
description: 'How Noor AI answers Islamic questions with citations it cannot fabricate'
---

<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

<span class="crescent">🌙</span>

# Noor AI

<div class="arabic">نور</div>
<div class="tagline">Your light to Islamic knowledge.</div>

<div class="meta">Serverless · Agentic RAG · AWS Bedrock · noorai.elprince.net</div>

<!--
Welcome! Today I'm walking you through Noor AI — a serverless, agentic RAG
application I built on AWS. "Noor" means light in Arabic. We'll cover the
architecture, the RAG design, and walk through the actual service code.
-->

---

## The Problem

LLMs answer religious questions **confidently** — and sometimes
**invent Quran verses and hadith that don't exist**.

> For a domain where *citation integrity is everything*, hallucination isn't a
> quirk. It's disqualifying.

### Noor AI's answer — three design decisions

1. **Agentic RAG** — the model must *search* primary sources with tools before answering
2. **Citations as data, not generation** — every chunk carries a citation computed at *ingestion time*
3. **Madhab awareness** — explicit treatment of *ikhtilaf* (scholarly difference), never false consensus

<!--
The core insight: don't try to make the model "more honest" — make fabrication
structurally impossible. Citations are data attached to retrieved text, not
something the model writes.
-->

---

## What You Get

<div class="cols">
<div>

### For the user
- Ask in **English or Arabic**
- Grounded in **Quran, Sahih al-Bukhari & Sahih Muslim**
- Inline citations — `[Quran 2:255]` — that are **real**
- Pick your **madhab** — hanafi, maliki, shafii, hanbali
- **Live agent steps** — watch it search the sources
- Token-by-token **streaming** answers

</div>
<div>

### For the engineer
- 100% serverless — **~$0.50/mo idle**
- **No Docker**, no API Gateway, no servers
- 5 single-responsibility CDK stacks
- ~630-line backend, strict SRP
- One command deploy: `cdk deploy --all`

</div>
</div>

---

<!-- _class: divider -->

<div class="kicker">Part One</div>

# Architecture

<div class="sub">Five stacks, one request path, zero idle cost</div>

---

<!-- _class: light -->
<!-- _footer: '' -->
<!-- _paginate: false -->

![bg fit](assets/architecture.svg)

<!--
Left to right: users hit Route 53 and CloudFront. Static frontend comes from
S3. API calls go to a streaming Lambda Function URL. The Lambda talks to
Bedrock — Claude for generation, a Knowledge Base for retrieval — and DynamoDB
for memory. Bottom: the offline ingestion pipeline.
-->

---

## One Request, End to End

```
User ─→ CloudFront ──→ /*      S3  (Next.js static export)
              └─────→ /api/*  Lambda Function URL  (streaming)
                                 │
                                 ▼
                        FastAPI + LangChain agent
                          │            │        │
                    search tools   InvokeModel  sessions
                          ▼            ▼        ▼
                   Bedrock KB      Claude     DynamoDB
                   (S3 Vectors)   Haiku 4.5   (TTL 72h)
```

- **Single origin** — the browser only ever talks to one domain. No CORS.
- **No buffering** — the token stream survives every hop untouched.

---

## Five Stacks, One Job Each

| Stack | Owns | Why separate |
|-------|------|--------------|
| `NoorAi-Dns` | Route 53 zone + ACM cert | us-east-1 constraint, one-time |
| `NoorAi-Data` | DynamoDB chat table | data outlives compute |
| `NoorAi-KnowledgeBase` | Corpus S3 + S3 Vectors + Bedrock KB | RAG storage is long-lived |
| `NoorAi-Api` | Lambda + Function URL + IAM | stateless, redeploy freely |
| `NoorAi-Web` | Frontend S3 + CloudFront | delivery only |

> Same philosophy as the backend code: **one unit, one responsibility** —
> tearing down compute never risks data.

---

<!-- _class: code -->

## Infra Highlight — FastAPI on Lambda, No Docker

The **Lambda Web Adapter** layer runs uvicorn inside the managed Python
runtime. A Function URL in `RESPONSE_STREAM` mode replaces API Gateway:

```ts
// infra/lib/api-stack.ts
const apiFunction = new lambda.Function(this, 'ApiFunction', {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: 'run.sh',                        // LWA startup script → uvicorn
  code: pythonLambdaCode(backendDir, ['src', 'run.sh']),
  layers: [lwaLayer],                       // AWS Lambda Web Adapter
  environment: {
    AWS_LWA_INVOKE_MODE: 'response_stream', // stream tokens to the client
    AWS_LWA_READINESS_CHECK_PATH: '/api/health',
  },
});

const fnUrl = apiFunction.addFunctionUrl({
  authType: lambda.FunctionUrlAuthType.NONE,     // CloudFront fronts it
  invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
});
```

**Simpler, cheaper, and it streams.** Python deps are bundled with `uv` at synth time.

---

<!-- _class: divider -->

<div class="kicker">Part Two</div>

# The RAG Corpus

<div class="sub">Citations you can't fabricate</div>

---

<!-- _class: code -->

## The Key Decision Lives at Ingestion Time

`build_corpus.py` splits raw dumps (Quran, Bukhari, Muslim) into **one file
per verse / per hadith** — about **21,000 sources** — each with a metadata sidecar:

```jsonc
// ingest/data/corpus/quran/2_255.json.metadata.json
{
  "metadataAttributes": {
    "citation":    { "value": { "stringValue": "Quran 2:255" } },
    "source_type": { "value": { "stringValue": "quran" } }
  }
}
```

- Retrieval units are **always whole verses/hadith** — never truncated or merged
- The `citation` is **precomputed and authoritative**
- At answer time the model *quotes* the citation from metadata — it never *composes* one

<!--
This is the anti-hallucination trick. The citation string travels with the
text through the whole pipeline. The model's job is to copy it, not write it.
-->

---

<!-- _class: code -->

## Vector Storage — S3 Vectors + Cohere

Multilingual embeddings so **Arabic and English queries** both land on the
right passages — stored in S3 Vectors, a fraction of OpenSearch's cost:

```ts
// infra/lib/knowledge-base-stack.ts
const vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
  vectorBucketName: vectorBucket.vectorBucketName!,
  indexName: VECTOR_INDEX_NAME,
  dataType: 'float32',
  dimension: 1024,               // Cohere Embed Multilingual v3
  distanceMetric: 'cosine',
});
```

### Ingestion pipeline — offline, idempotent, incremental

```
download_data.sh  →  build_corpus.py  →  sync.py
   raw dumps          43k files +         aws s3 sync +
                      citations           StartIngestionJob
```

---

<!-- _class: divider -->

<div class="kicker">Part Three</div>

# The Backend

<div class="sub">One class, one job — ~630 lines total</div>

---

## Service Map

```
app.py                  HTTP edge — validation, NDJSON streaming
└─ ChatService          orchestrator façade, the single entry point
   └─ ConversationChain the agentic turn: history → agent → events → persist
      ├─ AgentFactory       builds the tool-calling agent   (singleton)
      │  ├─ LLMService      ChatBedrockConverse             (singleton)
      │  ├─ RagToolset      @tool adapters: search_quran / search_hadith
      │  │  └─ RetrievalService   Bedrock Retrieve → domain objects
      │  │     └─ ContextBuilder  "[citation] text" evidence formatting
      │  └─ prompts/        citation + madhab rules
      ├─ MemoryService     DynamoDB-backed chat history
      └─ AgentEvent        the NDJSON wire contract
```

> Every box is **independently testable** — the toolset takes an injected
> retriever, the chain never touches boto3, the event shape lives in one file.

---

<!-- _class: code -->

## AgentFactory — Construction vs Execution

LangChain 1.0's `create_agent` wires model + tools + prompt into a compiled
graph. Built **once per Lambda container**, reused across invocations:

```python
class AgentFactory:
    _agent = None

    @classmethod
    def get_agent(cls):
        if cls._agent is None:
            cls._agent = create_agent(
                model=LLMService.get_model(),       # ChatBedrockConverse
                tools=RagToolset().as_tools(),      # search_quran, search_hadith
                system_prompt=AGENT_SYSTEM_PROMPT,  # citation + madhab rules
            )
        return cls._agent
```

- **Singleton pattern everywhere it pays** — model, agent, boto3 clients survive container reuse
- Construction stays separate from execution, so `ConversationChain` focuses on the turn itself

---

<!-- _class: code -->

## RagToolset — The Tools the Agent Calls

The **docstring is the interface** — it's what the model reads to decide
when and how to search:

```python
@tool
def search_quran(query: str) -> str:
    """Search the Quran for verses relevant to a topic or question.
    `query` is a concise concept, e.g. "reward of patience".
    Returns verses prefixed with their citation, e.g. [Quran 2:255]."""
    chunks = retriever.retrieve(query, source_type="quran")
    return ContextBuilder.build(chunks)
```

Output handed back to the model:

```
[Quran 2:255] Allah — there is no deity except Him, the Ever-Living...

[Quran 2:286] Allah does not burden a soul beyond that it can bear...
```

The bracketed prefix is *exactly* what the model reuses inline. **Copy, not compose.**

---

<!-- _class: code -->

## RetrievalService — Raw API → Domain Objects

The only class that touches `bedrock-agent-runtime`. Everything downstream
gets a clean, frozen dataclass:

```python
@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    citation: str      # authoritative — from ingestion-time metadata
    source_type: str   # "quran" | "hadith"
    score: float

class RetrievalService:
    @classmethod
    def retrieve(cls, query, source_type=None, top_k=None):
        vector_config = {"numberOfResults": top_k or config.retrieval_top_k}
        if source_type:                     # metadata filter per tool
            vector_config["filter"] = {
                "equals": {"key": "source_type", "value": source_type}}
        response = cls._get_client().retrieve(
            knowledgeBaseId=config.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": vector_config},
        )
        return [cls._to_chunk(r) for r in response.get("retrievalResults", [])]
```

---

<!-- _class: code -->

## ConversationChain — The Agentic Turn

**Load history → run agent → translate events → persist.** The heart of the backend:

```python
async def astream(self, question, session_id, school="general"):
    history = MemoryService.get_history(session_id)
    messages = self._build_messages(question, school, history.messages)

    answer_parts, tool_starts = [], {}
    async for ev in self._agent.astream_events({"messages": messages}, version="v2"):
        if ev["event"] == "on_chat_model_stream":
            text = LLMService.extract_text(ev["data"]["chunk"].content)
            if text:
                answer_parts.append(text)
                yield AgentEvent.token(text)
        elif ev["event"] == "on_tool_start":
            answer_parts.clear()            # pre-tool preamble — discard it
            tool_starts[ev["run_id"]] = time.monotonic()
            yield AgentEvent.tool_start(ev["run_id"], ev["name"], query)
        elif ev["event"] == "on_tool_end":
            ms = int((time.monotonic() - tool_starts.pop(ev["run_id"])) * 1000)
            yield AgentEvent.tool_end(ev["run_id"], ev["name"], ms, count)

    history.add_message(HumanMessage(content=question))
    history.add_message(AIMessage(content="".join(answer_parts)))
    yield AgentEvent.done()
```

<!--
Note the subtle detail: text the model emits BEFORE calling a tool — "Let me
search for that..." — is preamble. answer_parts.clear() discards it so only
the final grounded answer is persisted.
-->

---

<!-- _class: code -->

## AgentEvent — Own Your Wire Contract

The streaming protocol is defined **once**, used by producer and consumer.
One NDJSON line per event:

```python
@dataclass(frozen=True)
class AgentEvent:
    type: str   # "token" | "tool_start" | "tool_end" | "done" | "error"
    data: dict = field(default_factory=dict)

    def to_ndjson(self) -> str:
        return json.dumps({"type": self.type, **self.data}, ensure_ascii=False) + "\n"
```

What actually flows over the wire:

```json
{"type": "tool_start", "tool": "search_quran", "query": "pillars of Islam"}
{"type": "tool_end",   "tool": "search_quran", "ms": 312, "count": 5}
{"type": "token", "text": "The five pillars"}
{"type": "done"}
```

The UI renders *"Searching the Quran… 5 results · 312 ms"* **while** the answer streams.

---

<!-- _class: code -->

## MemoryService — DynamoDB Chat History

Implements LangChain's `BaseChatMessageHistory` on `(SessionId, MessageIndex)`.
TTL cleans up old sessions automatically:

```python
class DynamoDBChatHistory(BaseChatMessageHistory):

    def add_message(self, message: BaseMessage) -> None:
        count = self._table.query(            # next index = current count
            KeyConditionExpression="SessionId = :sid",
            ExpressionAttributeValues={":sid": self._session_id},
            Select="COUNT",
        )["Count"]
        self._table.put_item(Item={
            "SessionId": self._session_id,
            "MessageIndex": count,
            "MessageData": json.dumps(message_to_dict(message)),
            "TTL": int(time.time()) + config.session_ttl_hours * 3600,
        })
```

- One item per message → ordering is free, appends are cheap
- **Pay-per-request** billing, zero capacity planning

---

## The Prompt — Where Domain Rigor Lives

The system prompt encodes the scholarly rules the code can't:

<div class="cols">
<div>

### Citation discipline
- **Search first** — call the tools before answering anything scriptural
- Cite **only** bracketed references returned by the tools
- Primary texts ≠ madhab rulings — **never** cite a fiqh classification

</div>
<div>

### Madhab rigor
- State **ikhtilaf explicitly** — name each school's position
- Never claim consensus (*ijma'*) unless it genuinely exists
- Precise terms per school — Hanafi *wajib* ≠ *fard*
- Sensitive topics → advise a qualified scholar

</div>
</div>

> Every answer: **brief answer → evidence → ruling by madhab → practical conclusion.**

---

<!-- _class: divider -->

<div class="kicker">Part Four</div>

# Streaming, End to End

<div class="sub">No buffering, anywhere</div>

---

<!-- _class: code -->

## The Stream Survives Every Hop

```
Claude tokens → astream_events → AgentEvent NDJSON → FastAPI StreamingResponse
   → Lambda Web Adapter (response_stream) → Function URL (RESPONSE_STREAM)
   → CloudFront (caching disabled on /api/*) → fetch() ReadableStream → React
```

The frontend needs nothing but `fetch` — and the TypeScript union mirrors the
Python dataclass one-to-one:

```ts
// frontend/src/lib/api.ts — NoorApiClient.ask()
const reader = res.body.getReader();
let buffer = "";
for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  // split complete lines on "\n" → JSON.parse → onEvent(event)
}
```

```ts
export type AgentStreamEvent =
  | { type: "token"; text: string }
  | { type: "tool_start"; id: string; tool: string; query?: string }
  | { type: "tool_end"; id: string; tool: string; ms: number; count: number }
  | { type: "done" } | { type: "error"; detail: string };
```

<!--
One FastAPI subtlety: the first event is pulled eagerly, so pre-stream
failures surface as a proper HTTP 500 instead of a broken 200 stream.
-->

---

## Frontend — Next.js Static Export

No server, no SSR bill — just files on S3 behind CloudFront.

| Component | Role |
|-----------|------|
| `ChatWindow` | conversation view — tokens render as they arrive |
| `MessageBubble` | bracketed citations become styled chips |
| `SchoolSelector` | madhab preference, sent with every question |
| `Sidebar` + `chatStore` | session management (Zustand) |
| `AuroraBackground` | the pretty part ✨ |
| `lib/api.ts` | typed `NoorApiClient` — the NDJSON parser |

---

## What It Costs

Everything is pay-per-use. **Idle cost: ~$0.50/month** (the Route 53 zone).

| Item | At low traffic |
|------|----------------|
| Bedrock tokens — Claude Haiku 4.5 | the main variable · ~$1–8/mo |
| Embeddings — one-time ingestion | ~$1–2 for the full 43k-file corpus |
| S3 Vectors | ~10× cheaper than OpenSearch Serverless minimum |
| Lambda · DynamoDB · S3 · CloudFront | pennies |

> And the whole thing tears down with `cdk destroy` — nothing is precious.

---

## Five Principles To Take Away

1. **Trust is a data problem** — citations precomputed at ingestion, copied at answer time. Fabrication is structurally impossible.
2. **One class, one job** — a ~630-line backend where every piece is testable and replaceable.
3. **Singletons where Lambda rewards them** — model, agent, clients survive container reuse.
4. **Own your wire contract** — one event shape, defined once, mirrored in TypeScript.
5. **Serverless everything** — zero idle cost, one-command deploy, one-command teardown.

---

<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

<span class="crescent">🌙</span>

# Thank You

<div class="tagline">Questions, ideas, pull requests — all welcome.</div>

<div class="meta">noorai.elprince.net · built with AWS CDK, Bedrock & LangChain</div>

<!--
That's Noor AI. Links in the description — the repo, the live site, and the
technical deep-dive doc this presentation is based on. Thanks for watching!
-->
