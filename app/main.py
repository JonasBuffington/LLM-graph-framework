# app/main.py
import asyncio
import time
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from neo4j.exceptions import ServiceUnavailable
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import router as api_router
from app.db.driver import Neo4jDriver
from app.core.redis_client import RedisClient
from app.core.exceptions import NodeNotFoundException
from app.core.rag_config import VECTOR_DIMENSIONS
from app.core.limiter import limiter

MAX_RETRIES = 10
RETRY_DELAY = 3
INITIALIZATION_GRACE_PERIOD = 30
HEALTH_IDLE_THRESHOLD_SECONDS = 600
neo4j_ready_event = asyncio.Event()
_last_non_health_activity = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Logic ---
    # Start the Neo4j initialization in the background
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
        # --- Shutdown Logic ---
        if startup_task and not startup_task.done():
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task
        
        await Neo4jDriver.close_driver()
        await RedisClient.close_client()
        print("Successfully closed Neo4j and Redis connections.")

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
    """Ensure the required vector and property indexes exist before serving traffic."""
    async with driver.session() as session:
        check_vector_index_query = "SHOW INDEXES YIELD name WHERE toLower(name) = 'concept_embeddings' RETURN count(*) > 0 AS indexExists"
        result = await session.run(check_vector_index_query)
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
        print("Ensuring property index on userId exists...")
        await session.run("CREATE INDEX concept_userId IF NOT EXISTS FOR (n:Concept) ON (n.userId)")
        print("Database indexes are configured.")


app = FastAPI(
    title="GenAI Graph Framework API",
    description="A generalized, AI-powered knowledge graph framework.",
    version="1.0.0",
    lifespan=lifespan
)

# Add Limiter to the application state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Exempt all OPTIONS requests from rate limiting to prevent CORS preflight issues
app.state.limiter.exempt_methods = ["OPTIONS"]

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
    allow_headers=["Content-Type", "X-User-ID", "Idempotency-Key"],
)

@app.exception_handler(NodeNotFoundException)
async def node_not_found_exception_handler(request: Request, exc: NodeNotFoundException):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"message": exc.message},
    )

app.include_router(api_router.router)

@app.middleware("http")
async def track_activity(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/healthz"):
        global _last_non_health_activity
        _last_non_health_activity = time.time()
    return response

@app.get("/")
async def root():
    return {"message": "Welcome to the GenAI Graph Framework API"}

@app.get("/healthz", tags=["Health"], status_code=status.HTTP_200_OK)
async def health_check():
    """
    Returns the operational status of the service and indicates whether
    clients should keep polling.
    """
    idle_seconds = time.time() - _last_non_health_activity
    polling_allowed = idle_seconds < HEALTH_IDLE_THRESHOLD_SECONDS
    return {
        "status": "ok",
        "neo4j_ready": neo4j_ready_event.is_set(),
        "polling_allowed": polling_allowed,
        "idle_seconds": int(idle_seconds)
    }

@app.get("/redis-health", tags=["Health"], status_code=status.HTTP_200_OK)
async def redis_health_check():
    """Lightweight Redis readiness probe."""
    redis_client = RedisClient.get_client()
    try:
        pong = await redis_client.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis unavailable: {exc}"
        ) from exc
    return {"status": "ok", "ping": pong}
