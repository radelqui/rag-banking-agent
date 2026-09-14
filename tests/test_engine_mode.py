"""PLAN-0001 (integración): ENGINE_MODE selecciona RAG puro vs agente con tools.

Solo se testea la DECISIÓN (`_select_engine_mode`), sin construir nada real: elegir
mal la rama (exponer tools bancarias cuando no tocaba) es el riesgo real aquí, no la
construcción de LlamaIndexEngine/AgentEngine — eso ya lo cubren sus propios módulos
con dobles, y requiere BD/LLM reales (pragma: no cover, igual que LlamaIndexEngine).
"""
import app.main as main_module
from app.core.config import Settings
from app.main import _build_engine, _select_engine_mode, create_app


def test_default_engine_mode_is_rag():
    assert Settings().engine_mode == "rag"
    assert _select_engine_mode(Settings()) == "rag"


def test_engine_mode_agent_selected_from_settings():
    assert _select_engine_mode(Settings(engine_mode="agent")) == "agent"


def test_use_fake_engine_wins_over_agent_mode(monkeypatch):
    """Aunque ENGINE_MODE=agent, USE_FAKE_ENGINE=1 nunca debe construir un agente real."""
    monkeypatch.setenv("USE_FAKE_ENGINE", "1")
    assert _select_engine_mode(Settings(engine_mode="agent")) == "fake"


def test_use_fake_engine_wins_over_rag_mode(monkeypatch):
    monkeypatch.setenv("USE_FAKE_ENGINE", "1")
    assert _select_engine_mode(Settings(engine_mode="rag")) == "fake"


async def test_create_app_with_fake_engine_ignores_agent_mode(monkeypatch):
    """Regresión de extremo a extremo: app real, ENGINE_MODE=agent, sin BD/LLM disponibles.
    Si el guard de USE_FAKE_ENGINE fallara, esto intentaría tocar Anthropic/Postgres reales
    y la prueba fallaría por conexión, no pasaría en silencio.
    """
    monkeypatch.setenv("USE_FAKE_ENGINE", "1")
    monkeypatch.setenv("ENGINE_MODE", "agent")
    app = create_app()
    async with app.router.lifespan_context(app):
        from app.rag.engine import FakeEngine

        assert isinstance(app.state.engine, FakeEngine)
    assert app.state.engine is None


def test_build_engine_delegates_non_fake_modes_without_touching_real_infra(monkeypatch):
    """_build_engine no debe construir nada él mismo para 'rag'/'agent': delega en
    _construct_real_engine con el mode ya decidido. Se monkeypatchea esa construcción
    real para no depender de BD/LLM en un test unitario."""
    seen = {}

    def fake_construct(settings, mode):
        seen["mode"] = mode
        return "motor-construido"

    monkeypatch.setattr(main_module, "_construct_real_engine", fake_construct)

    assert _build_engine(Settings(engine_mode="agent")) == "motor-construido"
    assert seen["mode"] == "agent"


def test_invalid_engine_mode_fails_loud():
    """Literal en Settings: un valor fuera de {'rag','agent'} debe romper al arrancar,
    nunca degradar en silencio a un modo no pedido."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(engine_mode="algo-raro")
