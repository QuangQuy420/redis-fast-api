from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import jwt
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ALGORITHM,
    BLACKLIST_PREFIX,
    create_access_token,
    get_current_user_id,
    hash_password,
    revoke_token,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models import User
from app.redis_client import get_redis

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str

    model_config = {"from_attributes": True}


# ---------- Endpoints ----------

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = User(username=body.username, hashed_password=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token, _, _ = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Blacklist the current token in Redis.
    TTL = remaining token lifetime, so Redis auto-expires the key when the token
    would have expired anyway — the blacklist never grows unboundedly.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        # Already invalid — nothing to revoke.
        return

    await revoke_token(jti=payload["jti"], exp=payload["exp"], redis=redis)


@router.get("/me", response_model=UserResponse)
async def me(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/debug/blacklist", tags=["debug"])
async def list_blacklisted_tokens(redis: aioredis.Redis = Depends(get_redis)):
    """
    Dev-only: show all currently blacklisted token JTIs and their remaining TTL.
    Demonstrates that Redis auto-expires keys — no manual cleanup needed.
    """
    keys = await redis.keys(f"{BLACKLIST_PREFIX}*")
    result = {}
    for key in keys:
        ttl = await redis.ttl(key)
        raw = key.decode() if isinstance(key, bytes) else key
        jti = raw.removeprefix(BLACKLIST_PREFIX)
        result[jti] = {"ttl_seconds": ttl}
    return result
