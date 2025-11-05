# app/main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from neo4j.exceptions import ServiceUnavailable

from app.api import router as api_router # Updated import
from app.db.driver import Neo4jDriver
from app.core.exceptions import NodeNotFoundException
from app.core.rag_config import VECTOR_DIMENSIONS

MAX_RETRIES = 10
RETRY_DELAY = 3

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic with Retry ---
    driver = None
    for attempt in range(MAX_RETRIES):
        try:
            driver = await Neo4jDriver.get_driver()
            await driver.verify_connectivity()
            print("Successfully connected to Neo4j.")
            break
        except ServiceUnavailable:
            if attempt + 1 == MAX_RETRIES:
                print(f"Error: Could not connect to Neo4j after {MAX_RETRIES} attempts.")
                raise
            print(f"Neo4j not ready, retrying in {RETRY_DELAY} seconds... (Attempt {attempt + 1}/{MAX_RETRIES})")
            await asyncio.sleep(RETRY_DELAY)

    # --- Vector Index Creation ---
    if driver:
        async with driver.session() as session:
            check_index_query = "SHOW INDEXES YIELD name WHERE toLower(name) = 'concept_embeddings' RETURN count(*) > 0 AS indexExists"
            result = await session.run(check_index_query)
            record = await result.single()
            if not (record and record["indexExists"]):
                print("Vector index 'concept_embeddings' not found. Creating it now...")
                await session.run(
                    f"""
                    CREATE VECTOR INDEX `concept_embeddings`
                    FOR (n:Concept) ON (n.embedding)
                    OPTIONS {{ indexConfig: {{
                        `vector.dimensions`: {VECTOR_DIMENSIONS},
                        `vector.similarity_function`: 'cosine'
                    }} }}
                    """
                )
            else:
                print("Vector index 'concept_embeddings' already exists.")
    
    yield
    
    # --- Shutdown Logic ---
    await Neo4jDriver.close_driver()
    print("Successfully closed Neo4j connection.")


app = FastAPI(
    title="GenAI Graph Framework API", # Updated title
    description="A generalized, AI-powered knowledge graph framework.", # Updated description
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(NodeNotFoundException)
async def node_not_found_exception_handler(request: Request, exc: NodeNotFoundException):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"message": exc.message},
    )

# Include the single, unified router
app.include_router(api_router.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the GenAI Graph Framework API"}