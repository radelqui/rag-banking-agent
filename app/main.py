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


def _require_llm_credentials(settings) -> None:
    """Falla fuerte SI y SOLO SI faltan credenciales para el motor real ('rag'/'agent').

    Sin esto, Anthropic()/OpenAIEmbedding() se construyen "bien" con api_key=None:
    /health/ready da 200 y el fallo real solo aparece en el primer POST como
    "error interno" (excepción genérica en routes.py) — un banco no puede permitirse
    que un pod se anuncie listo sin poder responder. Se comprueba ANTES de importar
    nada de llama_index, así se prueba sin BD/red (a diferencia del resto de esta
    construcción, que sí requiere infraestructura real).
    """
    missing = [
        name
        for name, value in (
            ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            ("OPENAI_API_KEY", settings.openai_api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Faltan credenciales para arrancar el motor real "
            f"({', '.join(missing)}): revisa el K8s Secret/Vault del banco. "
            "El pod no debe llegar a 'ready' sin ellas."
        )


def _construct_real_engine(settings, mode: str):
    _require_llm_credentials(settings)
    return _assemble_real_engine(settings, mode)


def _assemble_real_engine(settings, mode: str):  # pragma: no cover - requiere BD+LLM reales
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
