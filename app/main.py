import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _select_engine_mode(settings) -> str:
    """'fake' | 'rag' | 'agent' — decide la rama sin construir nada (fácil de testear).

    USE_FAKE_ENGINE siempre gana: los tests y el desarrollo local nunca deben acabar
    construyendo un agente con tools reales por un ENGINE_MODE mal puesto en el entorno.
    """
    if os.getenv("USE_FAKE_ENGINE") == "1":
        return "fake"
    return "agent" if settings.engine_mode == "agent" else "rag"


def _construct_real_engine(settings, mode: str):  # pragma: no cover - requiere BD+LLM reales
    """'rag' o 'agent' con infraestructura real. Igual que LlamaIndexEngine (app.rag.engine),
    esto solo se ejercita con BD+credenciales reales (test de integración), no en unitarios."""
    from app.rag.engine import LlamaIndexEngine

    rag_engine = LlamaIndexEngine(settings)
    if mode == "rag":
        return rag_engine

    # mode == "agent" (PLAN-0001): mismas tools bancarias que RAG puro, más
    # get_account_balance/get_product_info atadas al customer_id autenticado.
    from llama_index.llms.anthropic import Anthropic

    from app.agent.runtime import AgentEngine
    from app.core.db import get_ai_engine

    llm = Anthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )
    return AgentEngine(get_ai_engine(), rag_engine, llm)


def _build_engine(settings):
    mode = _select_engine_mode(settings)
    if mode == "fake":
        from app.rag.engine import FakeEngine

        return FakeEngine()
    return _construct_real_engine(settings, mode)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.engine = _build_engine(settings)  # carga índices → readiness espera
    yield
    app.state.engine = None


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
