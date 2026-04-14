# Spiritbox — End-to-End System Walkthrough

A plain-English guide to what happens from the moment you click Record to the moment a reminder lands in your inbox.

---

## The Big Picture

```
Browser mic
    ↓  WebM/Opus audio file
FastAPI /ingest/audio
    ↓  Whisper API → plain text
LangGraph pipeline (4 agents in sequence)
    ├── Entity Extractor  (GPT-4o)  → dates, people, money amounts
    ├── Classifier        (GPT-4o)  → category tags per sentence
    ├── Intent Detector   (GPT-4o)  → should any of this trigger a reminder?
    │       ↓ yes → Firestore (save event) + Cloud Scheduler (book the job)
    └── Summarizer        (GPT-4o)  → 2–3 sentence digest
    ↓
pgvector (store entry + vector embedding for future semantic search)
    ↓
JSON response → frontend renders result

... later, automatically ...
Cloud Scheduler fires → Cloud Function → SendGrid email to you
```

---

## Step by Step

### Step 1 — Your browser captures the audio

**File:** `frontend/src/components/AudioRecorder.jsx`

When you click Record, the browser asks for microphone permission. While you speak, it collects audio in small 250ms chunks using the browser's built-in **MediaRecorder API**. The audio is encoded in **WebM/Opus** format — a modern compressed audio codec, like MP3 but more efficient.

When you click Stop, all those chunks are stitched together into a single audio blob sitting in memory in your browser tab. Nothing has been sent anywhere yet.

---

### Step 2 — The audio is sent to the backend

**File:** `frontend/src/api/client.js`

The audio blob is wrapped in a `multipart/form-data` HTTP request — the same format a browser uses when you upload a file through an HTML form. It's POSTed to:

```
POST /ingest/audio
```

on the FastAPI backend server. Think of it as attaching the audio file to an email and sending it.

---

### Step 3 — FastAPI receives it and transcribes it

**Files:** `app/api/routes/ingest.py`, `app/transcription/whisper.py`

FastAPI receives the audio file. It immediately hands it to the Whisper wrapper, which does three things:

1. Writes the audio to a **temporary file on disk** — the OpenAI API requires a real file path, not bytes in memory
2. Sends that file to **OpenAI Whisper** (`whisper-1` model) — the same technology powering YouTube auto-captions
3. Gets back a plain text string of your words, then deletes the temp file

From this point on, **audio and text entries are identical** — it's all just text going into the next stage.

---

### Step 4 — The LangGraph pipeline starts

**File:** `app/agents/graph.py`

LangGraph is an orchestration framework — it runs a sequence of AI agents in order, like an assembly line. Each station (agent) does one job and hands a shared "state" object to the next station.

The state object starts like this:

```json
{
  "raw_text": "I have a dentist appointment tomorrow at 10am...",
  "entities": {},
  "categories": [],
  "events": [],
  "summary": "",
  "entry_id": "abc-123",
  "model_used": {},
  "cache_hits": {}
}
```

Each agent receives this, fills in its field, and passes it on. By the end, every field is populated.

The pipeline order is:

```
Entity Extractor → Classifier → Intent Detector → Summarizer
```

---

### Step 5 — Agent 1: Entity Extractor

**File:** `app/agents/entity_extractor.py`

Sends your text to GPT-4o with a prompt that says:
> "Find all people, places, dates, times, money amounts, and events. Return structured JSON."

Example input:
> "I have a dentist appointment tomorrow at 10am. Paid rent 22000 rupees."

Example output added to state:
```json
{
  "events": [{"description": "dentist appointment", "datetime": "tomorrow 10:00"}],
  "amounts": [{"description": "rent", "amount": 22000, "currency": "INR"}]
}
```

This runs on **GPT-4o** (the more expensive, accurate model) because getting dates and amounts wrong would break everything downstream.

---

### Step 6 — Agent 2: Classifier

**File:** `app/agents/classifier.py`

Sends your text to GPT-4o with a prompt that says:
> "Tag each sentence with one or more life categories."

Available categories: `health`, `work`, `relationships`, `music`, `mental_health`, `finances`, `personal_growth`, `family`, `other`

Example output added to state:
```json
[
  {"sentence": "I have a dentist appointment tomorrow at 10am.", "categories": ["health"]},
  {"sentence": "Paid rent 22000 rupees.", "categories": ["finances"]}
]
```

A sentence can have more than one category. If nothing fits, it gets tagged `other`.

In the v2 design this will be downgraded to **GPT-4o-mini** (cheaper, faster) since classification doesn't require the same precision as extracting exact dates.

---

### Step 7 — Agent 3: Intent Detector

**File:** `app/agents/intent_detector.py`

Looks at the extracted entities and asks GPT-4o:
> "Should any of these events trigger a reminder email? If yes, what time should the reminder fire?"

If there's a schedulable event, it:

1. Computes `reminder_time = event_time - 1 hour` (configurable)
2. Saves the event to **Firestore** — Google's cloud NoSQL database. Think of it as a JSON document stored in the cloud with a document ID you can look up later.
3. Calls the **GCP Cloud Scheduler API** — this is like booking a calendar alarm in Google's infrastructure. You tell it: "at this exact datetime, make an HTTP POST to this URL."

The scheduler job is now sitting in GCP, waiting. The pipeline continues.

---

### Step 8 — Agent 4: Summarizer

**File:** `app/agents/summarizer.py`

Sends the full text to GPT-4o and asks for a 2–3 sentence human-readable digest of the entry, suitable for displaying in a feed. No extraction, no classification — just a clean summary.

This will also be downgraded to **GPT-4o-mini** in v2 since summarising doesn't require the full model's power.

---

### Step 9 — The entry is stored in pgvector

**File:** `app/memory/vector_store.py`

After the pipeline completes, the result is saved to **pgvector** — the PostgreSQL vector extension that turns our existing database into a vector store.

"Vector" means each entry is also stored as a list of ~1,500 numbers that mathematically encode the *meaning* of the text. This is called an **embedding**. Two pieces of text about similar topics will have embeddings that are numerically close to each other.

This is what enables semantic search later: you could ask "times I felt anxious" and it would find entries *about* anxiety even if you never used that exact word — because the meaning is similar, not just the words.

---

### Step 10 — The response returns to the frontend

The API sends back a JSON response:

```json
{
  "entry_id": "abc-123",
  "summary": "You have a dentist appointment tomorrow and paid rent.",
  "categories": ["health", "finances"],
  "entities": {"events": [...], "amounts": [...]},
  "events": [{"event_description": "dentist appointment", ...}]
}
```

The frontend renders this — you see your summary and category tags appear on screen.

---

### Step 11 — The reminder fires (hours or days later, automatically)

**File:** `functions/send_reminder/main.py`

When the scheduled time arrives, **GCP Cloud Scheduler** makes an HTTP POST to a **Cloud Function** — a tiny piece of code deployed separately from the main server that runs only when called (serverless). It:

1. Reads the event details from the request body
2. Sends a reminder email via **SendGrid** (a transactional email service)
3. Marks the event as `reminded = true` in Firestore so it doesn't fire again

You get an email in your inbox.

---

## Why So Many Separate Agents?

You might wonder why there are four separate LLM calls instead of one big prompt that does everything.

The answer is **separation of concerns**:

- Each agent has one focused job, which makes it easier to test independently
- You can measure each one's accuracy separately (does the classifier get the right tags? does the entity extractor get dates right?)
- You can improve or swap one agent without touching the others
- You can route each agent to a different model — cheap/fast for simple tasks, expensive/accurate for critical ones
- When something goes wrong, you know exactly which agent failed

This separation is the core of what makes it a proper **LLMOps** system rather than a script that calls GPT once.

---

## The Services and What They Do

| Service | What it is | What Spiritbox uses it for |
|---|---|---|
| OpenAI Whisper | Speech-to-text model | Transcribing your voice recordings |
| GPT-4o | Large language model | Running all 4 agents |
| GPT-4o-mini | Cheaper/faster LLM (v2) | Classifier and Summarizer agents |
| LangGraph | Agent orchestration framework | Running agents in sequence, managing state |
| pgvector | PostgreSQL vector extension | Storing entries + semantic search |
| Firestore | Google's NoSQL cloud database | Storing scheduled events/reminders |
| Cloud Scheduler | GCP cron-style job scheduler | Booking reminder jobs at exact times |
| Cloud Functions | Serverless compute (GCP) | The code that actually fires the reminder |
| SendGrid | Transactional email service | Sending reminder emails |
| LangFuse | LLM observability platform | Tracking every prompt, trace, and eval score |
| FastAPI | Python web framework | The backend API server |
| React + Vite | Frontend framework | The web UI |
| Cloud Run | Serverless container hosting (GCP) | Running the FastAPI server in production |

---

## Glossary

**Vector / Embedding** — A list of numbers that represents the meaning of a piece of text. Used to find semantically similar content without exact keyword matching.

**LLM (Large Language Model)** — A model like GPT-4o trained on vast amounts of text. You send it a prompt and it generates a response. Spiritbox uses it to classify, extract, detect intent, and summarise.

**Agent** — A function that sends a prompt to an LLM, parses the response, and returns structured output. Spiritbox has four: entity extractor, classifier, intent detector, summariser.

**LangGraph** — A library for building multi-agent pipelines where agents hand a shared state object between them in a defined order.

**Semantic search** — Finding content based on meaning rather than keywords. "I was stressed" would match "I felt overwhelmed" because they mean similar things.

**Serverless** — Code that runs only when called, not on a permanently-running server. Cloud Functions and Cloud Run are both serverless — GCP spins them up on demand and shuts them down when idle.

**Multipart/form-data** — An HTTP format for sending files in a request. The same format used when you attach a file to an HTML form.

**WebM/Opus** — A modern compressed audio format that browsers use natively. Smaller file sizes and better quality than MP3 at equivalent bitrates.

**LangFuse** — A platform that records every LLM call (input prompt, output, model used, cost, latency). Spiritbox uses it to track prompt versions, run evaluations, and detect if model quality degrades over time.
