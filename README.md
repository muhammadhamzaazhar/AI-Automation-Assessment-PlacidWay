---
title: PlacidWay Knowledge Chatbot
emoji: 💬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Answers from PlacidWay pages, with source links
---

# PlacidWay Knowledge Chatbot

A chatbot that answers visitor questions using only the 7 PlacidWay pages we were given. Every answer
links to its source page. If the pages don't cover a question, the bot says so and offers a free quote.

- **Live demo:** _add URL_
- **Test results:** [TEST_RESULTS.md](TEST_RESULTS.md)
- **Limitations and next steps:** [WRITEUP.md](WRITEUP.md)

## Run locally

Needs Python 3.11+ and an OpenAI API key.

```bash
python -m venv venv
venv\Scripts\activate              # macOS/Linux: source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # then put your OPENAI_API_KEY in .env
uvicorn app.api:app --reload
```

Open http://localhost:8000. The knowledge base is already built, so no crawling is needed.

| Command | What it does |
|---|---|
| `python -m scripts.ingest` | Re-crawl the 7 pages and rebuild the knowledge base |
| `python -m scripts.run_eval` | Run the test questions and write `TEST_RESULTS.md` |
| `pytest` | Run the unit tests (offline, no API key needed) |

## How it works

1. **Ingestion:** crawls the URLs in `config/sources.yaml` (follows robots.txt and its 10-second
   crawl delay), keeps only the page content, drops menus and "related clinics" carousels, splits the
   text into chunks and embeds them.
2. **Understand:** the first LLM call finds the intent and rewrites follow-ups ("what about recovery
   time?") into full questions. Booking, medical advice, greetings and off-topic questions get fixed
   replies.
3. **Search:** hybrid search (embeddings + keywords) picks the 10 most relevant chunks.
4. **Answer:** the second LLM call answers only from those chunks and lists the chunks it used.
5. **Check:** code verifies that every number in the answer appears in the chunks. If one doesn't,
   the bot says it doesn't know instead. Source links come from the chunks, never from the LLM.

Also included: answers in the visitor's language, a medical disclaimer (shown once), lead capture
(name and email), and a log of unanswered questions.

## Refresh content

Run `python -m scripts.ingest`, then commit and push the updated `data/` folder (the deployed site
picks it up on redeploy). On a server with a writable disk (Docker, Hugging Face) you can instead
call the live site:

```bash
curl -X POST https://<your-url>/admin/refresh -H "X-Admin-Token: <ADMIN_TOKEN>"
```

There, `REFRESH_INTERVAL_HOURS` refreshes automatically. Other admin endpoints:
`GET /admin/unanswered` (questions the bot couldn't answer) and `GET /admin/leads`.

## Tools and models

| Tool | Why |
|---|---|
| Python, FastAPI, plain HTML/JS | Small and easy to follow; no framework hiding the logic |
| OpenAI `gpt-6-luna` | Structured output makes answers checkable; fast and about $0.001 per question (change with `LLM_MODEL`) |
| OpenAI `text-embedding-3-small` + BM25 | Embeddings match meaning, keywords match exact terms (e.g. "adrenal" vs "anal") |
| BeautifulSoup | Exact control over which parts of a page count as content |
| SQLite | Stores leads and unanswered questions with no setup |

## Project structure

```
app/api.py            web server and endpoints
app/ingest/           crawler, extractor, chunker, pipeline
app/retrieval/        embeddings and hybrid search
app/chat/             understand → search → answer → check
app/static/           chat UI
config/sources.yaml   the 7 source URLs
data/                 extracted pages (readable .md files) and the built index
eval/cases.yaml       test questions
scripts/              ingest, run_eval, chat (terminal chat)
tests/                unit tests
```

## Deploy

- **Vercel:** import the repo (preset: FastAPI, default settings) and add `OPENAI_API_KEY` and
  `ADMIN_TOKEN` as environment variables. Vercel's disk is read-only, so to refresh content run
  `python -m scripts.ingest` locally and push; leads and logs are kept in `/tmp` (temporary).
- **Docker / Hugging Face Spaces:** create a Docker Space, add the same two secrets and push this
  repository. Here `/admin/refresh` updates the content live.
