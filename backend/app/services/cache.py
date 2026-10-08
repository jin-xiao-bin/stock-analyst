"""可选 Redis 缓存（未配置则透明降级为直查）"""
import functools
import hashlib
import json
import logging

from ..config import settings

log = logging.getLogger(__name__)
try:
    import redis
except ImportError:
    redis = None

_pool = None
if settings.redis_url and redis:
    try:
        _pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
        redis.Redis(connection_pool=_pool).ping()
        log.info("Redis 缓存已启用")
    except Exception as e:  # noqa: BLE001
        log.warning("Redis 不可用, 降级直查: %s", e)
        _pool = None


def cache_json(ttl_seconds: int = 86400):
    """装饰器：结果需可 JSON 序列化"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if _pool is None:
                return fn(*args, **kwargs)
            key_src = f"{fn.__module__}.{fn.__qualname__}:{args}:{sorted(kwargs.items())}"
            key = "cache:" + hashlib.md5(key_src.encode()).hexdigest()
            r = redis.Redis(connection_pool=_pool)
            hit = r.get(key)
            if hit:
                return json.loads(hit)
            val = fn(*args, **kwargs)
            try:
                r.setex(key, ttl_seconds, json.dumps(val, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                pass
            return val
        return wrapper
    return deco
