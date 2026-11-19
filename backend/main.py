import asyncio
import os
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from auth.config import Settings
from auth.store import Accounts
from auth.routes import router
from ai.service import AI, AIError
from ai.routes import router as ai_router
from repos.jobs import Jobs
from repos.routes import router as repositories_router
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import PyMongoError


@asynccontextmanager
async def lifespan(app):
    with MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), timeoutMS=2500, connect=False) as mongo:
        async with httpx.AsyncClient(base_url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=2.5) as qdrant:
            app.state.mongo = mongo
            app.state.qdrant = qdrant
            app.state.settings = Settings.load()
            app.state.accounts = await asyncio.to_thread(Accounts, mongo.repomind)
            app.state.jobs = Jobs(mongo.repomind.repositories)
            app.state.ai = AI(mongo.repomind)
            await asyncio.to_thread(app.state.ai.setup)
            await app.state.jobs.start()
            indexer = asyncio.create_task(app.state.ai.worker())
            try:
                yield
            finally:
                await app.state.jobs.stop()
                app.state.ai.stop_event.set()
                await indexer
                app.state.ai.provider.close()


app = FastAPI(title="RepoMind AI", lifespan=lifespan)


app.include_router(router)
app.include_router(repositories_router)
app.include_router(ai_router)


@app.exception_handler(AIError)
async def provider_error(request, exc):
    return JSONResponse({"detail":str(exc)},status_code=503)


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/auth/", "/api/repositories", "/api/conversations")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation(request, exc):
    if request.url.path.startswith("/api/conversations"):
        return JSONResponse({"detail":"Enter a question between 1 and 2000 characters."},status_code=422)
    if request.url.path.startswith("/api/repositories"):
        return JSONResponse({"detail": "Submit a valid GitHub repository URL."}, status_code=422)
    # FastAPI validation errors can include raw request inputs.
    return JSONResponse({"detail": "Check your email, username and password requirements."}, status_code=422)


@app.exception_handler(PyMongoError)
async def database_unavailable(request, exc):
    return JSONResponse({"detail": "Database unavailable. Please try again."}, status_code=503)


async def probe(check):
    start = perf_counter()
    try:
        await check()
        return {"online": True, "ms": round((perf_counter() - start) * 1000)}
    except (PyMongoError, httpx.HTTPError, TimeoutError):
        return {"online": False, "ms": None}


@app.get("/api/health")
async def health():
    async def mongo_ping():
        await asyncio.to_thread(app.state.mongo.admin.command, "ping")

    async def qdrant_ready():
        response = await app.state.qdrant.get("/readyz")
        response.raise_for_status()

    mongo, qdrant = await asyncio.gather(probe(mongo_ping), probe(qdrant_ready))
    ready = mongo["online"] and qdrant["online"]
    return JSONResponse({"ready": ready, "services": {"mongodb": mongo, "qdrant": qdrant}},
                        status_code=200 if ready else 503, headers={"Cache-Control": "no-store"})
