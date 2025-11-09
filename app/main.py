# app/main.py
import asyncio
from contextlib import asynccontextmanager, suppress
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
INITIALIZATION_GRACE_PERIOD = 30
neo4j_ready_event = asyncio.Event()

@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_task = asyncio.create_task(_initialize_neo4j())

    try:
        await asyncio.wait_for(startup_task, timeout=INITIALIZATION_GRACE_PERIOD)
    except asyncio.TimeoutError:
        print(
            "Neo4j initialization is taking longer than expected. "
            "Continuing startup while initialization finishes in the background."
        )
    except Exception as exc:
        print(f"Neo4j initialization task raised an unexpected error: {exc}")

    try:
        yield
    finally:
        if startup_task:
            if not startup_task.done():
                startup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await startup_task
            else:
                # Drain any exception to avoid "Task exception was never retrieved" warnings.
                exc = startup_task.exception()
                if exc:
                    print(f"Neo4j initialization task completed with error: {exc}")
        await Neo4jDriver.close_driver()
        print("Successfully closed Neo4j connection.")

async def _initialize_neo4j():
    """Attempt to verify Neo4j connectivity and ensure the vector index exists."""
    neo4j_ready_event.clear()
    driver = None
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Initializing Neo4j (attempt {attempt + 1}/{MAX_RETRIES})...")
            driver = await Neo4jDriver.get_driver()
            await driver.verify_connectivity()
            print("Successfully connected to Neo4j.")
            await _ensure_vector_index(driver)
            print("Neo4j initialization complete.")
            neo4j_ready_event.set()
            return
        except ServiceUnavailable as exc:
            if attempt + 1 == MAX_RETRIES:
                print(f"Error: Could not connect to Neo4j after {MAX_RETRIES} attempts. Last error: {exc}")
                raise
            backoff = RETRY_DELAY * (attempt + 1)
            print(f"Neo4j not ready ({exc}). Retrying in {backoff} seconds...")
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            print("Neo4j initialization task cancelled.")
            raise
        except Exception as exc:
            print(f"Unexpected error while initializing Neo4j: {exc}")
            raise

async def _ensure_vector_index(driver):
    """Ensure the required vector index exists before serving traffic."""
    async with driver.session() as session:
        check_index_query = (
            "SHOW INDEXES YIELD name WHERE toLower(name) = 'concept_embeddings' "
            "RETURN count(*) > 0 AS indexExists"
        )
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


app = FastAPI(
    title="GenAI Graph Framework API", # Updated title
    description="A generalized, AI-powered knowledge graph framework.", # Updated description
    version="1.0.0",
    lifespan=lifespan
)

allowed_origins = [
    "http://localhost:8000",
    "http://localhost:8080",
    "https://jonasbuffington.github.io",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "neo4j_ready": neo4j_ready_event.is_set()}
