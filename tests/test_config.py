from app.core.config import Settings
from app.rag.vector_store import parse_db_url


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("LLAMAINDEX_DATABASE_URL", "postgresql+asyncpg://ro:pw@db:5432/banco")
    s = Settings(_env_file=None)
    assert s.llamaindex_database_url.startswith("postgresql+asyncpg://ro:")


def test_parse_db_url():
    p = parse_db_url("postgresql+asyncpg://ai_ro:s3cret@pg.svc:5433/banco")
    assert p == {"user": "ai_ro", "password": "s3cret", "host": "pg.svc", "port": 5433, "database": "banco"}


def test_llm_gateway_settings_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://llm-gw.banco.local")
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5")
    s = Settings(_env_file=None)
    assert s.anthropic_base_url == "https://llm-gw.banco.local" and s.llm_model == "claude-opus-5"
