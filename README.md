# GenAI Graph Explorer

Simple knowledge-graph playground that pairs FastAPI, Neo4j, and Google Gemini. You can create concepts, expand them with RAG-aware LLM calls, and tweak the prompt template right from the UI.

## Live Links
- Frontend: https://jonasbuffington.github.io/GenAI-Graph-Explorer/
- API root: https://llm-graph-framework.onrender.com/
- Swagger: https://llm-graph-framework.onrender.com/docs

## What it currently does
- Store concept nodes + labeled edges in Neo4j.
- “Expand node”:
  - grabs the selected node,
  - pulls structural neighbors (1-hop) from Neo4j,
  - pulls semantic neighbors from the `concept_embeddings` vector index (cosine similarity on Gemini embeddings),
  - feeds that context + the editable prompt to `gemini-flash-latest`,
  - ingests the returned JSON nodes/edges back into the graph.
- Keep the workspace prompt editable (and resettable to `app/core/prompts.py`) through the REST API and frontend tab.
- Frontend (Cytoscape + dagre) shows the graph, lets you add/delete nodes, and triggers expansions with loading feedback.

## Stack
- FastAPI, Uvicorn, Poetry.
- Google `google-genai` SDK (Gemini Flash + `gemini-embedding-001`).
- Neo4j 5 + APOC vector index (`concept_embeddings` auto-created on startup).
- Frontend: vanilla HTML/CSS/JS, Cytoscape.js.
- Docker + docker-compose for local Neo4j/API, Render for hosting, GitHub Pages for static files.

## Quick Start
Create `.env`:
```env
NEO4J_URI=bolt://localhost:7687         # or neo4j+s://... for Aura
NEO4J_USER=neo4j
NEO4J_PASSWORD=*****
GEMINI_API_KEY=...
```

Run locally (with optional Neo4j container):
```bash
poetry install
docker compose up neo4j -d   # optional if you have local Aura creds
poetry run uvicorn app.main:app --reload
cd frontend && python -m http.server 8080
```
When the frontend is on `localhost`, it calls the local API. Any other origin (e.g., GitHub Pages) automatically uses the Render URL.
