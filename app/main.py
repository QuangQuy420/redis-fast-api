import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.redis_client import connect_redis, disconnect_redis, get_redis
from app.routers import todo


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_redis()
    yield
    await disconnect_redis()


app = FastAPI(
    title="Redis Learning API",
    description="FastAPI + PostgreSQL + Redis — playground for learning Redis patterns.",
    version="0.1.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t0
    print(f"{request.method} {request.url.path} — {elapsed * 1000:.1f}ms")
    return response


app.include_router(todo.router)


@app.get("/health", tags=["infra"])
async def health():
    status = {"postgres": "unreachable", "redis": "unreachable"}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = str(e)

    try:
        r = await get_redis()
        await r.ping()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = str(e)

    overall = "ok" if all(v == "ok" for v in status.values()) else "degraded"
    return {"status": overall, **status}
