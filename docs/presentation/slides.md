---
marp: true
theme: noor
paginate: true
footer: 'Noor AI · noorai.elprince.net'
title: 'Noor AI — Serverless Agentic RAG on AWS'
description: 'Portfolio walkthrough: an agentic RAG system with citations it cannot fabricate'
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
Hi, I'm [name]. This is Noor AI — a serverless, agentic RAG application I
designed, built, and shipped end to end on AWS: infrastructure, backend,
frontend, and the data pipeline. "Noor" means light in Arabic. In the next
few minutes: what it does, the engineering decisions behind it, and a few
pieces of code I'm proud of.
-->

---

## The Problem

LLMs answer religious questions **confidently** — and sometimes
**invent Quran verses and hadith that don't exist**.

> For a domain where *citation integrity is everything*, hallucination isn't a
> quirk. It's disqualifying.

Prompting the model to "be honest" doesn't fix this.

### So I made fabrication *structurally impossible*

The model **searches** primary sources with tools, and every citation it shows
is **data retrieved from the corpus** — never text the model composed.

<!--
The thesis of the whole project: trust is a data problem, not a prompting
problem. Everything else in this video follows from that one decision.
-->

---

<!-- _class: divider -->

<div class="kicker">Seeing is believing</div>

# 🎬 Live Demo

<div class="sub">Watch it think — agent steps, streaming tokens, real citations</div>

<!--
[CUT TO SCREEN RECORDING — suggested beats, ~90 seconds]
1. Ask "What are the pillars of Islam?" — point out the agent steps appearing
   live: "Searching the Quran… 5 results · 312 ms", then tokens streaming.
2. Hover the citation chips — [Quran 2:255], [Sahih al-Bukhari 8],
   [Sahih Muslim 16] — these are retrieved, not generated.
3. Follow-up: "tell me more about the third one" — conversation memory.
4. Switch madhab to Hanafi, ask about witr prayer — the ruling leads with the
   Hanafi position and names where schools differ.
5. Optionally: ask in Arabic — multilingual embeddings handle it.
-->

---

<!-- _class: code -->

## The Core Idea — Copy, Not Compose

The anti-hallucination work happens at **ingestion time**, not answer time.
The corpus — Quran, Sahih al-Bukhari, Sahih Muslim — is split into
**one file per verse / per hadith** (~21,000 sources), each with a
**precomputed citation** in a metadata sidecar:

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
- The citation travels *with the text* through the entire pipeline
- The model's job is to **copy** the bracketed reference — it never writes one

<!--
This is the idea I'd defend in a design review. You can't prompt your way to
citation integrity — but you can make the citation a property of the data.
-->

---

<!-- _class: light -->
<!-- _footer: '' -->
<!-- _paginate: false -->

![bg fit](assets/architecture.svg)

<!--
The whole system, end to end. Users come in through Route 53 and CloudFront.
Static frontend from S3; /api/* goes to a streaming Lambda Function URL
running FastAPI and a LangChain agent. The agent calls Bedrock — Claude for
generation, a Knowledge Base over S3 Vectors for retrieval — and DynamoDB
holds conversation memory. Bottom: the offline ingestion pipeline.
Five CDK stacks, one responsibility each — all TypeScript, one command deploy.
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
- **No buffering** — Claude's tokens survive every hop untouched, all the way to React.

---

## Decisions & Tradeoffs

Every row here had a default answer — and a reason to reject it:

| Chose | Over | Because |
|-------|------|---------|
| Lambda **Function URL** + Web Adapter | API Gateway | native response streaming, less config, cheaper |
| **S3 Vectors** | OpenSearch Serverless | ~10× cheaper at this corpus size, zero idle cost |
| **Citations precomputed** at ingestion | prompt-only guardrails | fabrication structurally impossible |
| **Agentic tools** | one-shot RAG | model refines queries, searches Quran & hadith independently |
| Host bundling with **uv** | Docker images | faster deploys, no daemon, same Lambda target |
| **Static export** + CloudFront | SSR hosting | zero server cost, single origin |

<!--
This slide is the engineering judgment slide. Each choice was made against a
more common default, with a concrete reason. Happy to go deep on any of these.
-->

---

<!-- _class: divider -->

<div class="kicker">Three pieces of code</div>

# Inside the Agent

<div class="sub">~630 lines of backend, one class one job</div>

---

## Service Map — One Class, One Job

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

## Code Moment 1 — The Docstring *Is* the Interface

In agentic systems, tools aren't called by your code — they're called by the
**model**, and what it reads is the docstring:

```python
@tool
def search_quran(query: str) -> str:
    """Search the Quran for verses relevant to a topic or question.
    `query` is a concise concept, e.g. "reward of patience".
    Returns verses prefixed with their citation, e.g. [Quran 2:255]."""
    chunks = retriever.retrieve(query, source_type="quran")
    return ContextBuilder.build(chunks)
```

What the model gets back:

```
[Quran 2:255] Allah — there is no deity except Him, the Ever-Living...
```

The bracketed prefix is *exactly* what it reuses inline. **Copy, not compose** —
enforced by the shape of the data the tool returns.

<!--
Writing for a model as the caller changes how you think about API design.
The docstring is prompt engineering. The return format is the contract.
-->

---

<!-- _class: code -->

## Code Moment 2 — The Agentic Turn

One event loop translates the agent's internals into UI-ready events.
Subtle detail: text emitted *before* a tool call is preamble — discarded:

```python
async for ev in self._agent.astream_events({"messages": messages}, version="v2"):

    if ev["event"] == "on_chat_model_stream":       # answer tokens
        answer_parts.append(text)
        yield AgentEvent.token(text)

    elif ev["event"] == "on_tool_start":            # agent decided to search
        answer_parts.clear()     # "Let me look that up…" — not the answer
        yield AgentEvent.tool_start(run_id, tool_name, query)

    elif ev["event"] == "on_tool_end":              # results are in
        yield AgentEvent.tool_end(run_id, tool_name, ms, result_count)

history.add_message(AIMessage(content="".join(answer_parts)))
yield AgentEvent.done()
```

Only the final grounded answer is persisted to memory — same rule the UI applies.

<!--
This is the heart of the backend. Understanding what an agent framework emits,
and shaping it into a clean product experience, is the actual agentic
engineering work.
-->

---

<!-- _class: code -->

## Code Moment 3 — Own Your Wire Contract

The streaming protocol is one NDJSON line per event, defined **once** in
Python, mirrored one-to-one in TypeScript:

```json
{"type": "tool_start", "tool": "search_quran", "query": "pillars of Islam"}
{"type": "tool_end",   "tool": "search_quran", "ms": 312, "count": 5}
{"type": "token", "text": "The five pillars"}
{"type": "done"}
```

That contract survives every hop with **no buffering anywhere**:

```
Claude tokens → LangChain events → NDJSON → FastAPI StreamingResponse
  → Lambda Web Adapter → Function URL (RESPONSE_STREAM)
  → CloudFront → fetch() ReadableStream → React
```

The UI renders *"Searching the Quran… 5 results · 312 ms"* **while** the answer streams —
that's the whole product experience, built on this one contract.

---

## Engineering Habits (the code you didn't see)

- **Singletons where Lambda rewards them** — model, agent, and boto3 clients are built once per container and reused across invocations
- **Domain objects over SDK shapes** — one class touches `bedrock-agent-runtime`; everything downstream gets a frozen `RetrievedChunk` dataclass
- **Errors surface honestly** — the first stream event is pulled eagerly, so failures return a real HTTP 500, not a broken 200 stream
- **Data outlives compute** — DynamoDB and the corpus live in separate stacks; redeploying the API can never touch them

> Full walkthrough of every service — with code — in the
> [Technical Deep Dive](../DEEP_DIVE.md) linked below.

---

## Domain Rigor — Encoded in the Prompt

The system prompt carries the scholarly rules code can't express:

<div class="cols">
<div>

### Citation discipline
- **Search first** — tools before any scriptural claim
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

> Getting the domain right mattered as much as getting the code right.

---

## What I'd Build Next

Shipping taught me what production agentic systems actually need:

<div class="cols">
<div>

### Evaluation — the biggest gap
- **Golden question set** with expected citations, run on every change
- **Citation-accuracy checks** — does every bracket match a retrieved chunk?
- Madhab-correctness review with qualified scholars

</div>
<div>

### Hardening
- **Tracing** for agent steps (OTel / LangSmith) + token-cost dashboards
- **Guardrails** — off-domain refusal tests, input moderation
- Auth + per-session rate limiting
- More collections — the Sunan collections, tafsir sources

</div>
</div>

<!--
For agentic AI work, evals ARE the test suite. This is the first thing I'd
add with more time, and the first thing I'd expect to build at work.
-->

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

## Three Takeaways

1. **Trust is a data problem** — citations are precomputed at ingestion and copied at answer time. Fabrication is structurally impossible, not just discouraged.

2. **Agentic engineering is interface design for a model** — docstrings are the API, return formats are the contract, and the event stream is the product.

3. **Judgment is choosing what *not* to use** — no API Gateway, no Docker, no OpenSearch, no servers. Every omission was a decision with a reason.

---

<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: '' -->

<span class="crescent">🌙</span>

# Thank You

<div class="tagline">Repo, live site, and technical deep dive — links in the description.</div>

<div class="meta">noorai.elprince.net · built with AWS CDK, Bedrock & LangChain</div>

<!--
That's Noor AI — designed, built, and shipped end to end. If you're hiring
for agentic AI engineering, I'd love to talk. Thanks for watching!
-->
