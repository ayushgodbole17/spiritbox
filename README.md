# Spiritbox

A production-grade personal AI agent for journaling and life management.

## Phase 1 — Core Loop

Phase 1 implements the end-to-end ingest pipeline:

```
Audio/Text → Whisper (audio only) → LangGraph pipeline → Weaviate (vector store)
                                          |
                    entity_extractor → classifier → intent_detector → summarizer
```

### Project structure

```
spiritbox/
  app/
    main.py              FastAPI entry point
    config.py            Pydantic settings (loaded from .env)
    api/routes/
      ingest.py          POST /ingest/text, POST /ingest/audio
      entries.py         GET /entries, GET /entries/{id}, GET /entries/search
      reminders.py       GET /reminders
    agents/
      graph.py           LangGraph supervisor
      entity_extractor.py  (stub)
      classifier.py        (stub)
      intent_detector.py   (stub)
      summarizer.py        (stub)
    memory/
      vector_store.py    Weaviate client
      buffer.py          Conversation buffer (LangChain)
    scheduler/
      create_job.py      GCP Cloud Scheduler wrapper
    email/
      sendgrid.py        SendGrid wrapper
    events/
      firestore.py       Firestore events store
    transcription/
      whisper.py         OpenAI Whisper wrapper
    prompts/             Prompt templates for Phase 2
  functions/
    send_reminder/       GCP Cloud Function
  tests/                 pytest suite + golden dataset
  .github/workflows/     CI/CD (test → build → deploy)
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

### 3. Start Weaviate (Docker)

```bash
docker-compose up weaviate -d
```

### 4. Run the API

```bash
uvicorn app.main:app --reload --port 8080
```

API docs: http://localhost:8080/docs

### 5. Run tests

```bash
pytest tests/ -v
```

## Docker

Run the full stack (API + Weaviate):

```bash
docker-compose up --build
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Liveness probe |
| POST | /ingest/text | Ingest text journal entry |
| POST | /ingest/audio | Ingest audio journal entry |
| GET | /entries | List recent entries |
| GET | /entries/search?q=... | Semantic search |
| GET | /entries/{id} | Get entry by ID |
| GET | /reminders | List upcoming reminders |

## Environment variables

See `.env.example` for the full list with descriptions.

## Deployment

Push to `main` triggers the GitHub Actions pipeline:
1. Run tests
2. Build and push Docker image to GCR
3. Deploy to Cloud Run
4. Deploy `send_reminder` Cloud Function

Set the following GitHub secrets:
- `GCP_PROJECT_ID`
- `GCP_SA_KEY` (service account JSON)
- Individual secrets for API keys (see `deploy.yml`)

## Roadmap

- **Phase 2**: Wire real LLM calls into all four agents using the prompt templates in `app/prompts/`.
- **Phase 3**: Add conversational interface, proactive nudges, mobile push notifications.
