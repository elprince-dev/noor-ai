# Noor AI — YouTube Video Script

Paired with `slides.md` (18 slides). Target runtime: **6.5–7.5 minutes** at a
relaxed speaking pace (~140 wpm). Total narration ≈ 1,050 words.

## Production notes

- Record narration in **four chunks** (marked below) — easier retakes.
- Record the **demo first**; adjust the demo narration to what actually happens.
- If you flub a line: pause 2 seconds, repeat the sentence, keep rolling. Cut in edit.
- Speak like you're explaining to a colleague, not presenting to a board.
- Optional: webcam bubble during Chunk 1 and Chunk 4 only.

---

## CHUNK 1 — Hook & Demo (~2 min)

### Slide 1 — Title

> Hi, I'm [NAME]. This is Noor AI — an agentic RAG application I designed,
> built, and shipped end to end on AWS: the infrastructure, the backend, the
> frontend, and the data pipeline. "Noor" means *light* in Arabic. In the next
> few minutes I'll show you what it does, the engineering decisions behind it,
> and three pieces of code I think are worth your time.

### Slide 2 — The Problem

> Here's the problem it solves. If you ask a large language model a religious
> question, it answers confidently — and sometimes it invents Quran verses or
> hadith that simply don't exist. In most domains hallucination is a quality
> issue. In this one, it's disqualifying.
>
> And you can't fix it by telling the model to be honest. So I took a
> different approach: I made fabricating a citation *structurally impossible*.
> The model has to search the primary sources with tools, and every citation
> you see is data retrieved from the corpus — never text the model wrote.
> Let me show you what that looks like.

### Slide 3 — 🎬 DEMO CUTAWAY (~90 seconds of screen recording)

Demo beats — narrate over the recording:

> This is the live app. I'll ask: *"What are the pillars of Islam?"*
>
> Watch the top of the response — before answering, the agent decides to
> search. You can see it live: searching the Quran… five results in about
> three hundred milliseconds… now the hadith collections — Bukhari and Muslim.
> Then the answer streams in token by token.
>
> These bracketed citations — Quran 2:255, Sahih al-Bukhari 8, Sahih Muslim 16
> — are retrieved data, not generated text.
>
> It also has memory — I'll follow up with *"tell me more about the third
> one"* and it knows what "the third one" refers to.
>
> One more thing: I'll switch the school of thought to Hanafi and ask about
> witr prayer. Notice the answer now leads with the Hanafi position and
> explicitly names where the other schools differ — no fake consensus.

---

## CHUNK 2 — The Idea & The Architecture (~2 min)

### Slide 4 — The Core Idea: Copy, Not Compose

> So how does that citation guarantee actually work? The trick is that the
> anti-hallucination work happens at *ingestion time*, not at answer time.
>
> The corpus — the full Quran, Sahih al-Bukhari, and Sahih Muslim — is split
> into one file per verse and per hadith. About twenty-one thousand sources.
> Each one carries a metadata sidecar with a precomputed citation string.
>
> That citation travels *with the text* through the whole pipeline. When the
> model uses a passage, its job is to copy the bracketed reference — it never
> composes one. I think of it as: trust is a data problem, not a prompting
> problem.

### Slide 5 — Architecture Diagram

> Here's the whole system. Users come in through Route 53 and CloudFront. The
> static frontend is served from S3. API calls go to a Lambda Function URL
> running FastAPI and a LangChain agent. The agent talks to Bedrock — Claude
> for generation, and a Knowledge Base over S3 Vectors for retrieval — with
> DynamoDB holding conversation memory. At the bottom, the offline ingestion
> pipeline that builds and syncs the corpus.
>
> It's five CDK stacks in TypeScript, each with a single responsibility, and
> the whole thing deploys with one command.

### Slide 6 — One Request, End to End

> Two properties of this design I care about. First, single origin — the
> browser only ever talks to one domain, so there's no CORS anywhere. Second,
> no buffering — Claude's tokens survive every hop untouched, from Bedrock all
> the way to React.

### Slide 7 — Decisions & Tradeoffs

> This slide is the one I'd defend in a design review. Every row had a
> default answer — and a reason to reject it. A Lambda Function URL instead
> of API Gateway, because it streams natively and costs less. S3 Vectors
> instead of OpenSearch Serverless — about ten times cheaper at this corpus
> size, with zero idle cost. Bundling with uv instead of Docker. A static
> export instead of SSR hosting. None of these are exotic — the point is each
> one was a *decision*, not a default.

---

## CHUNK 3 — Three Pieces of Code (~2 min)

### Slide 8 — Divider: Inside the Agent

> The backend is about six hundred and thirty lines, one class one job. I'll
> show you three moments from it.

### Slide 9 — Service Map

> First, the shape. Every box here is independently testable — the toolset
> takes an injected retriever, the conversation chain never touches raw AWS
> SDK calls, and the streaming event shape lives in exactly one file.

### Slide 10 — Code Moment 1: The Docstring Is the Interface

> Moment one. In an agentic system, tools aren't called by your code —
> they're called by the *model*. And what the model reads is the docstring.
> So this docstring isn't documentation — it's the API contract, and writing
> it is prompt engineering. Notice the return format too: every result comes
> back prefixed with its bracketed citation. The data shape itself enforces
> copy-not-compose.

### Slide 11 — Code Moment 2: The Agentic Turn

> Moment two — the event loop at the heart of the backend. It translates the
> agent framework's internal events into clean UI events: answer tokens, tool
> starts, tool ends.
>
> My favorite detail is this `answer_parts.clear()`. When a model decides to
> call a tool, it often says something first, like "let me look that up."
> That's preamble, not answer. Discarding it on every tool start means only
> the final grounded answer gets persisted to memory — and the UI applies the
> same rule.

### Slide 12 — Code Moment 3: Own Your Wire Contract

> Moment three — the streaming protocol. One NDJSON line per event, defined
> once in Python, mirrored one-to-one in TypeScript. This little contract is
> what makes the product experience possible: the UI can show "searching the
> Quran, five results, three hundred milliseconds" *while* the answer is still
> streaming — because tool events and tokens travel on the same wire.

---

## CHUNK 4 — Judgment & Close (~1.5 min)

### Slide 13 — Engineering Habits

> A few habits from the code you didn't see: singletons where Lambda rewards
> them, so the model and clients survive across invocations. Domain objects
> instead of raw SDK shapes. Errors that surface as real HTTP 500s instead of
> broken streams. And data living in separate stacks from compute, so a
> redeploy can never touch it. There's a full written deep dive linked below.

### Slide 14 — Domain Rigor

> One thing I learned building this: getting the domain right mattered as much
> as the code. The system prompt encodes rules a fiqh student would recognize —
> never claim scholarly consensus unless it exists, use each school's precise
> terminology, and never attach a scriptural citation to a juristic ruling.

### Slide 15 — What I'd Build Next

> And I want to be honest about the biggest gap: evaluation. If I kept going,
> the first thing I'd build is an eval suite — a golden set of questions with
> expected citations, run on every change, plus a citation-accuracy check that
> verifies every bracket in an answer maps to a chunk that was actually
> retrieved. For agentic systems, evals are the test suite. After that:
> tracing, guardrails, and more source collections.

### Slide 16 — Cost

> Cost, briefly — because serverless was the point. Idle cost is about fifty
> cents a month. Under real usage it's a few dollars, almost all of it Bedrock
> tokens. And the entire thing tears down with one command.

### Slide 17 — Three Takeaways

> If you remember three things: trust is a data problem — solve it in the
> pipeline, not the prompt. Agentic engineering is interface design where the
> caller is a model. And judgment often shows up as what you *don't* use.

### Slide 18 — Thank You

> That's Noor AI. The repo, the live site, and the written deep dive are all
> linked in the description. If you're hiring for agentic AI engineering, I'd
> love to talk. Thanks for watching.

---

## Recording checklist

- [ ] 1920×1080, browser fullscreen (`F` in the Marp HTML view)
- [ ] Mic check — record 10 s, listen back, kill background noise
- [ ] Demo recorded and reviewed before narrating Chunk 1
- [ ] OBS scenes: slides / demo / (optional) webcam bubble
- [ ] Edit: trim silences, stitch demo after Slide 3, export 1080p
- [ ] YouTube description: live URL, repo URL, DEEP_DIVE.md link, chapter timestamps
