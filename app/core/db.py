"""Dos motores de BD: uno normal para la API, otro de solo lectura para la IA."""
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

_app_engine: AsyncEngine | None = None
_ai_engine: AsyncEngine | None = None


def get_app_engine() -> AsyncEngine:  # pragma: no cover - requiere PostgreSQL
    global _app_engine
    if _app_engine is None:
        _app_engine = create_async_engine(get_settings().app_database_url, pool_pre_ping=True)
    return _app_engine


def get_ai_engine() -> AsyncEngine:  # pragma: no cover - requiere PostgreSQL
    """Motor que se entrega a LlamaIndex / tools. Credenciales de solo lectura."""
    global _ai_engine
    if _ai_engine is None:
        _ai_engine = create_async_engine(
            get_settings().llamaindex_database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=0,
        )
    return _ai_engine
