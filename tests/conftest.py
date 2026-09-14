import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import router
from app.rag.engine import FakeEngine


def make_app(engine) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    return app


@pytest.fixture
def fake_engine():
    return FakeEngine(tokens=["Su saldo", " es 100 EUR."])


@pytest.fixture
async def client(fake_engine):
    app = make_app(fake_engine)
    headers = {"X-Customer-Id": "C123"}  # identidad que pondría la pasarela del banco
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers) as c:
        yield c
