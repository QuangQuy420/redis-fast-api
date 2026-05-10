import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import redis.asyncio as aioredis

from app.config import settings
from app.redis_client import get_redis

bearer_scheme = HTTPBearer()

ALGORITHM = "HS256"

# Key pattern for the blacklist in Redis
# Using jti (JWT ID) keeps the key small — no need to store the full token.
BLACKLIST_PREFIX = "blacklist:"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: int) -> tuple[str, str, int]:
    """
    Returns (encoded_token, jti, exp_unix_timestamp).
    jti (JWT ID) uniquely identifies this token — used as the blacklist key.
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)
    return token, jti, int(expire.timestamp())


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    redis: aioredis.Redis = Depends(get_redis),
) -> int:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    jti: str = payload["jti"]

    # O(1) Redis lookup — the key exists only if this token was explicitly revoked.
    # Fail-open: if Redis is down, log and allow the request rather than returning 500.
    try:
        if await redis.exists(f"{BLACKLIST_PREFIX}{jti}"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Redis blacklist check failed: {e}")

    return int(payload["sub"])


async def revoke_token(jti: str, exp: int, redis: aioredis.Redis) -> None:
    """
    Add jti to Redis blacklist with TTL = remaining lifetime of the token.
    When the token would have expired naturally, Redis auto-deletes the key —
    no cleanup job needed.
    """
    remaining_ttl = exp - int(datetime.now(timezone.utc).timestamp())
    if remaining_ttl > 0:
        await redis.setex(f"{BLACKLIST_PREFIX}{jti}", remaining_ttl, "1")
