import pytest
from fastapi import HTTPException

from app.main import redis_health_check, RedisClient


class DummyRedis:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.pings = 0

    async def ping(self):
        self.pings += 1
        if self.should_fail:
            raise RuntimeError("boom")
        return "PONG"


@pytest.mark.asyncio
async def test_redis_health_success(monkeypatch):
    dummy = DummyRedis()

    monkeypatch.setattr(RedisClient, "get_client", classmethod(lambda cls: dummy))

    result = await redis_health_check()
    assert result == {"status": "ok", "ping": "PONG"}
    assert dummy.pings == 1


@pytest.mark.asyncio
async def test_redis_health_failure(monkeypatch):
    dummy = DummyRedis(should_fail=True)
    monkeypatch.setattr(RedisClient, "get_client", classmethod(lambda cls: dummy))

    with pytest.raises(HTTPException) as exc:
        await redis_health_check()

    assert "Redis unavailable" in str(exc.value.detail)
