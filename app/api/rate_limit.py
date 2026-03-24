import logging
import os
from functools import lru_cache

import redis
from fastapi import Depends, HTTPException, Request, Response, status
from redis.exceptions import RedisError

from app.api.deps import get_current_user
from app.models.user import User


logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@lru_cache(maxsize=1)
def _redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def _consume_limit(bucket: str, limit: int, window_seconds: int) -> tuple[int, int]:
    client = _redis_client()
    count = client.incr(bucket)
    if count == 1:
        client.expire(bucket, window_seconds)

    ttl = client.ttl(bucket)
    if ttl is None or ttl < 0:
        ttl = window_seconds
    return int(count), int(ttl)


def _apply_headers(response: Response, limit: int, remaining: int, retry_after: int):
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
    response.headers["Retry-After"] = str(max(1, retry_after))


def _enforce_limit(bucket: str, limit: int, window_seconds: int, response: Response):
    try:
        count, ttl = _consume_limit(bucket, limit, window_seconds)
    except RedisError:
        logger.exception("Rate limiter unavailable for bucket %s", bucket)
        return

    remaining = limit - count
    _apply_headers(response, limit, remaining, ttl)

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(max(1, ttl))},
        )


def rate_limit_by_ip(limit: int, window_seconds: int, scope: str):
    def dependency(request: Request, response: Response):
        client_ip = _get_client_ip(request)
        bucket = f"rate:{scope}:ip:{client_ip}"
        _enforce_limit(bucket, limit, window_seconds, response)

    return dependency


def rate_limit_by_user(limit: int, window_seconds: int, scope: str):
    def dependency(
        response: Response,
        current_user: User = Depends(get_current_user),
    ):
        bucket = f"rate:{scope}:user:{current_user.id}"
        _enforce_limit(bucket, limit, window_seconds, response)

    return dependency


def rate_limit_by_user_and_path(limit: int, window_seconds: int, scope: str, path_param: str):
    def dependency(
        request: Request,
        response: Response,
        current_user: User = Depends(get_current_user),
    ):
        resource_id = request.path_params.get(path_param, "unknown")
        bucket = f"rate:{scope}:user:{current_user.id}:{path_param}:{resource_id}"
        _enforce_limit(bucket, limit, window_seconds, response)

    return dependency
