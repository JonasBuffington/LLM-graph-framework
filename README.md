# GenAI Graph Explorer

GenAI Graph Explorer is a small playground for building a personal knowledge graph and letting Gemini suggest new nodes and edges. The backend is FastAPI + Neo4j, the frontend is a static page powered by Cytoscape.js, and everything is deployed on Render/GitHub Pages for convenience.

## Live Links
- Frontend: https://jonasbuffington.github.io/GenAI-Graph-Explorer/
- API root: https://llm-graph-framework.onrender.com/
- Swagger docs: https://llm-graph-framework.onrender.com/docs

## Features
- CRUD for nodes and edges stored in Neo4j.
- “Expand” action that:
  - collects the selected nodes,
  - builds a context list with 1-hop graph neighbors,
  - finds semantic neighbors via Gemini embeddings and a Neo4j vector index,
  - calls Gemini Flash with that context,
  - sanitizes the AI JSON output (escapes LaTeX, drops “thought-signature” noise),
  - saves the generated nodes/edges back into the graph.
- Per-user prompt editing through the API and frontend, with a reset option to the repo default.
- Built-in rate limiting and Redis-backed idempotency so POST/PUT/DELETE/PATCH requests can be retried safely.
- Health endpoints for Render (`/healthz`) and Redis (`/redis-health`), plus frontend UI messaging for slow cold-starts.

## Stack Overview
- **Backend**: FastAPI, Uvicorn, SlowAPI for rate limiting, Redis for idempotency cache + limiter storage, Neo4j driver, and Google `google-genai` SDK (Gemini Flash + `gemini-embedding-001`).
- **Data**: Neo4j 5 with a `concept_embeddings` vector index created on startup and per-user graph partitions.
- **Frontend**: vanilla HTML/CSS/JS with Cytoscape.js for visualization, dagre layout, and a small UX layer (loading overlays, client-generated `X-User-ID`, automatic `Idempotency-Key` headers, graceful Render wake-up messaging).
- **Dev/Deploy**: Poetry-managed Python project, Dockerfile that runs Redis + the API in one container, docker-compose for local Neo4j/Redis/API, GitHub Pages for the static site, Render free tier for the backend.

## Getting Started Locally
1. Create `.env` in the repo root:
   ```env
   NEO4J_URI=bolt://localhost:7687      # or neo4j+s://... for Aura
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=*****
   REDIS_URL=redis://127.0.0.1:6379/0
   GEMINI_API_KEY=...
   ```
2. Install dependencies and start services:
   ```bash
   poetry install
   docker compose up neo4j redis -d   # optional if you already have these
   poetry run uvicorn app.main:app --reload
   ```
3. Run the frontend (from `frontend/`):
   ```bash
   python -m http.server 8080
   ```
   When accessed from `localhost`, the frontend calls the local API; any other origin falls back to the Render URL.

## Redis and Idempotency Notes
- `start.sh` launches Redis using `redis.conf`, waits for `redis-cli ping`, then starts Uvicorn. The `/redis-health` endpoint returns 200 when Redis responds with `PONG`.
- The custom `IdempotentAPIRoute` stores responses in Redis for 24 hours and enforces short-lived locks to prevent duplicate in-flight requests. Set `IDEMPOTENCY_DEBUG=true` to log cache hits/misses.
- SlowAPI rate limits default to Redis storage so counters survive restarts.

## Testing
Basic unit tests live under `tests/` and are run with Pytest:
```bash
pytest
```

They currently cover the AI response parser, structured-output extraction, Redis health check logic, and the idempotent route wrapper.

---

This project is still evolving, but it already shows how a simple FastAPI + Neo4j backend can work with Gemini to keep a graph-structured workspace growing. Contributions, suggestions, or bug reports are welcome.
