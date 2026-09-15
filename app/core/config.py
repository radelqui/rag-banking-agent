"""Configuración: SOLO lee variables de entorno. Sin secretos hardcodeados.

Las variables las inyecta el pipeline CI/CD / Kubernetes Secret / Vault.
El código conoce los NOMBRES; los VALORES los pone el banco al arrancar el contenedor.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rag-banking-agent"
    # "rag": solo recuperación documental (sin tools). "agent": añade tools bancarias
    # (PLAN-0001, get_account_balance/get_product_info) atadas al cliente autenticado.
    # Literal en vez de str: un valor inválido falla fuerte al arrancar, no degrada mudo.
    engine_mode: Literal["rag", "agent"] = "rag"
    # Conexión normal de la API (lectura/escritura)
    app_database_url: str = Field(default="postgresql+asyncpg://app:app@localhost:5432/banco")
    # Conexión RESTRINGIDA (solo SELECT) para LlamaIndex / tools del LLM
    llamaindex_database_url: str = Field(default="postgresql+asyncpg://ai_ro:ro@localhost:5432/banco")

    # --- Identidad: cabecera que rellena la pasarela del banco tras autenticar (OAuth2/AD)
    identity_header: str = "X-Customer-Id"

    # --- Modelos de frontera. En el banco NUNCA salen a internet: van por su pasarela.
    #     *_base_url vacío = proveedor directo (solo desarrollo). En producción: URL de la pasarela.
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    llm_model: str = "claude-opus-5"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    embed_model: str = "text-embedding-3-small"

    embed_dim: int = 1536
    vector_table: str = "documentos_bancarios"
    similarity_top_k: int = 5
    llm_timeout_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
