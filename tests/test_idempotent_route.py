from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import idempotency as idempotency_module
from app.api.idempotency import IdempotentAPIRoute


class StubRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key: str):
        self.store.pop(key, None)


def build_app():
    app = FastAPI()
    app.router.route_class = IdempotentAPIRoute

    @app.post("/echo")
    async def echo(payload: dict):
        return payload

    return app


HEADERS = {
    "X-User-ID": "user-1",
    "Idempotency-Key": "key-1",
}


def test_idempotent_route_caches_response(monkeypatch):
    redis_client = StubRedis()
    monkeypatch.setattr(idempotency_module, "get_redis_client", lambda: redis_client)

    client = TestClient(build_app())

    payload = {"value": "first"}
    first = client.post("/echo", json=payload, headers=HEADERS)
    assert first.status_code == 200
    assert first.json() == payload

    second = client.post("/echo", json={"value": "second"}, headers=HEADERS)
    assert second.status_code == 200
    assert second.json() == payload
