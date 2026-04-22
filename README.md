# Spiritbox

A production-grade personal AI agent for journaling and life management.

## What it does

```
Audio/Text → Whisper (audio) → LangGraph pipeline → pgvector
                                     |
              entity_extractor → classifier → intent_detector → summarizer → habit_tracker
                                     |
                              scheduled events → Cloud Scheduler → send_reminder Cloud Function
```

Ingested entries feed a RAG chat agent (hybrid search + SSE streaming) and a
weekly theme rollup that surfaces in the Insights tab.

### Project structure

```
spiritbox/
  app/
    main.py                  FastAPI entry point + lifespan hooks
    config.py                Pydantic settings
    api/routes/
      ingest.py              POST /ingest/text, POST /ingest/audio (202 + job poll)
      entries.py             GET /entries, /entries/{id}, /entries/search (PATCH, DELETE)
      reminders.py           GET /reminders
      chat.py                POST /chat, POST /chat/stream (SSE)
      habits.py              GET /api/habits, /api/habits/{id}
      digest.py              GET /api/digest/weekly + POST /weekly/run
      admin.py               /api/admin/{evals, metrics, analytics, costs, reminders/dlq, rollup/weekly, ...}
      auth.py                Google OAuth + JWT
    agents/
      graph.py               LangGraph supervisor
      entity_extractor.py    GPT-4o structured entities
      classifier.py          Sentence-level category tagging
      intent_detector.py     Scheduling-intent + reminder creation
      summarizer.py          2-3 sentence summaries
      habit_tracker.py       Streak/cadence tracking
      chat_agent.py          RAG chat (hybrid search + streaming)
      theme_summarizer.py    Weekly cosine clustering → themed rollups
    llm/
      router.py              Tier-1/Tier-2 model router with cascade
      cache.py               Semantic cache (stampede-protected)
      resilience.py          tenacity retries + circuit breakers
      guardrails.py          PII redaction + prompt-injection classifier
      token_tracker.py       Per-request token + cost bookkeeping
    memory/
      vector_store.py        pgvector + hybrid search (RRF)
    jobs/
      queue.py               In-process asyncio background worker
    observability/
      metrics.py             Request latency recorder + p50/p95 helpers
    middleware/
      correlation.py         X-Request-ID propagation
      rate_limit.py          Per-IP token bucket
    transcription/whisper.py
    email/sendgrid.py
    scheduler/               Cloud Scheduler wrapper
    prompts/                 Versioned prompt templates
  alembic/                   Schema migrations
  evals/                     Eval harness + LLM-as-judge
  functions/
    send_reminder/           Cloud Function: email reminders, writes to DLQ on failure
    weekly_rollup/           Cloud Function: triggers /admin/rollup/weekly
  frontend/                  Vite + React client (Write / History / Ask / Insights tabs)
  tests/                     pytest suite + golden dataset
  .github/workflows/         CI/CD (test → build → deploy)
```

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run the API

```bash
uvicorn app.main:app --reload --port 8080
```

API docs: http://localhost:8080/docs

### 4. Run tests

```bash
pytest tests/ -v
```

## Docker

Run the full stack (API + PostgreSQL/pgvector + frontend):

```bash
docker-compose up --build
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET  | /health                           | Liveness probe |
| GET  | /ready                            | Readiness (DB + OpenAI) |
| POST | /ingest/text                      | Ingest text journal entry |
| POST | /ingest/audio                     | Enqueue audio entry; returns 202 + job_id |
| GET  | /ingest/jobs/{job_id}             | Poll audio ingest status |
| GET  | /entries                          | List recent entries |
| GET  | /entries/search?q=...             | Hybrid (semantic + keyword) search |
| GET  | /entries/{id}                     | Get entry by ID |
| PATCH / DELETE | /entries/{id}           | Edit / delete (auth-scoped) |
| POST | /chat                             | RAG chat over past entries |
| POST | /chat/stream                      | Streaming variant (SSE) |
| GET  | /reminders                        | List upcoming reminders |
| GET  | /api/habits                       | Tracked habits + streaks |
| GET  | /api/digest/weekly                | Weekly insights digest |
| POST | /api/digest/weekly/run            | Manually trigger a rollup |
| GET  | /api/admin/analytics              | Aggregate stats + p50/p95 latency |
| POST | /api/admin/rollup/weekly          | Cron entry point for weekly themes |
| POST | /api/admin/reminders/dlq/{id}/retry | Replay a failed reminder from DLQ |

## Observability & safety

- **Auth**: Google OAuth → JWT; all entry/reminder routes scoped by `user_id`.
- **Guardrails**: PII redaction before LLM calls; prompt-injection classifier on chat.
- **Resilience**: tenacity retries + circuit breakers around OpenAI / Whisper / SendGrid.
- **Metrics**: per-request `request_metrics` rows with p50/p95 exposed via `/admin/analytics`.
- **Tracing**: LangFuse `@observe` spans across the pipeline; `X-Request-ID` propagated onto each trace so structured logs and traces are joinable.
- **Reminder DLQ**: SendGrid failures land in `reminder_dead_letters` (Cloud Scheduler gets a 200 so it stops retrying into the same hole); admin can replay.
- **Evals**: LLM-as-judge gate in `evals/`; CI blocks merges that regress classifier precision or entity F1.

## Environment variables

See `.env.example` for the full list with descriptions.

## Deployment

Push to `main` triggers the GitHub Actions pipeline:
1. Run tests
2. Build and push Docker image to GCR
3. Deploy to Cloud Run
4. Deploy `send_reminder` + `weekly_rollup` Cloud Functions

Set the following GitHub secrets:
- `GCP_PROJECT_ID`
- `GCP_SA_KEY` (service account JSON)
- Individual secrets for API keys (see `deploy.yml`)

Cloud Scheduler jobs to wire manually:
- `send_reminder` — invoked per-event by the intent detector
- `weekly_rollup` — weekly (e.g. Sunday 20:00 in user TZ) → calls the `weekly_rollup` function
