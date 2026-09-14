import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if os.getenv("USE_FAKE_ENGINE") == "1":
        from app.rag.engine import FakeEngine

        app.state.engine = FakeEngine()
    else:
        from app.rag.engine import LlamaIndexEngine

        app.state.engine = LlamaIndexEngine(settings)  # carga índices → readiness espera
    yield
    app.state.engine = None


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
