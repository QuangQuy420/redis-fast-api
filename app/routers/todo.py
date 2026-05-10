import json
import time
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Todo
from app.redis_client import get_redis

CACHE_TTL = 300      # seconds
RATE_LIMIT = 60      # requests
RATE_WINDOW = 60     # seconds


async def safe_redis(coro, default=None):
    try:
        return await coro
    except Exception as e:
        print(f"Redis error: {e}")
        return default


async def rate_limit(request: Request, redis: aioredis.Redis = Depends(get_redis)):
    key = f"rate_limit:{request.client.host}"
    count = await safe_redis(redis.incr(key))
    if count == 1:
        await safe_redis(redis.expire(key, RATE_WINDOW))
    if count is not None and count > RATE_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")


# ---------- Schemas ----------

class TodoCreate(BaseModel):
    title: str
    description: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    completed: bool | None = None


class TodoResponse(BaseModel):
    id: int
    title: str
    description: str | None
    completed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


router = APIRouter(prefix="/todos", tags=["todos"], dependencies=[Depends(rate_limit)])


# ---------- Endpoints ----------

@router.get("/", response_model=list[TodoResponse])
async def list_todos(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    t0 = time.perf_counter()
    cached = await safe_redis(redis.get("todos:list"))
    print(f"  Redis get: {(time.perf_counter() - t0) * 1000:.1f}ms")

    if cached:
        t1 = time.perf_counter()
        result = [TodoResponse.model_validate_json(item) for item in json.loads(cached)]
        print(f"  Deserialize cache: {(time.perf_counter() - t1) * 1000:.1f}ms")
        return result

    t1 = time.perf_counter()
    result = await db.execute(select(Todo).order_by(Todo.created_at.desc()))
    todos = result.scalars().all()
    print(f"  DB query: {(time.perf_counter() - t1) * 1000:.1f}ms")

    t2 = time.perf_counter()
    responses = [TodoResponse.model_validate(t) for t in todos]
    await safe_redis(redis.setex("todos:list", CACHE_TTL, json.dumps([r.model_dump_json() for r in responses])))
    print(f"  Serialize + Redis set: {(time.perf_counter() - t2) * 1000:.1f}ms")

    return responses


@router.get("/{todo_id}", response_model=TodoResponse)
async def get_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    cache_key = f"todo:{todo_id}"
    cached = await safe_redis(redis.get(cache_key))
    if cached:
        print(f"Cache hit for {cache_key}")
        return TodoResponse.model_validate_json(cached)

    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

    response = TodoResponse.model_validate(todo)
    await safe_redis(redis.setex(cache_key, CACHE_TTL, response.model_dump_json()))
    return response


@router.post("/", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
async def create_todo(
    body: TodoCreate,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    todo = Todo(title=body.title, description=body.description)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    await safe_redis(redis.delete("todos:list"))
    return todo


@router.patch("/{todo_id}", response_model=TodoResponse)
async def update_todo(
    todo_id: int,
    body: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(todo, field, value)

    await db.commit()
    await db.refresh(todo)
    await safe_redis(redis.delete(f"todo:{todo_id}", "todos:list"))
    return todo


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    todo = await db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    await db.delete(todo)
    await db.commit()
    await safe_redis(redis.delete(f"todo:{todo_id}", "todos:list"))
