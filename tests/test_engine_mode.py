"""PLAN-0001 (integración): ENGINE_MODE selecciona RAG puro vs agente con tools.

Se testea la DECISIÓN (`_select_engine_mode`) y el GUARD de credenciales
(`_require_llm_credentials`) sin construir nada real: elegir mal la rama (exponer
tools bancarias cuando no tocaba) o arrancar "listo" sin credenciales son el riesgo
real aquí, no la construcción en sí de LlamaIndexEngine/AgentEngine — eso ya lo
cubren sus propios módulos con dobles, y sí requiere BD/LLM reales (pragma: no
cover, igual que LlamaIndexEngine).
"""
import pytest
from pydantic import ValidationError

import app.main as main_module
from app.core.config import Settings, get_settings
from app.main import _build_engine, _require_llm_credentials, _select_engine_mode, create_app


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
    with pytest.raises(ValidationError):
        Settings(engine_mode="algo-raro")


# --- B1 (hallazgo del verificador sobre 97ede33): sin credenciales, ENGINE_MODE=agent
# arrancaba "listo" y cada POST fallaba en silencio ("error interno"). Debe fallar
# fuerte AL ARRANCAR, antes de tocar BD/LLM reales.


def test_require_llm_credentials_raises_when_both_missing():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _require_llm_credentials(Settings(anthropic_api_key=None, openai_api_key=None))


def test_require_llm_credentials_raises_when_only_one_missing():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _require_llm_credentials(Settings(anthropic_api_key="sk-ant-x", openai_api_key=None))


def test_require_llm_credentials_passes_when_both_present():
    _require_llm_credentials(Settings(anthropic_api_key="sk-ant-x", openai_api_key="sk-oai-x"))


def test_construct_real_engine_never_touches_infra_without_credentials(monkeypatch):
    """El guard corta ANTES de _assemble_real_engine: si se llamara a la construcción
    real sin credenciales, este test lo detectaría (se rompería por conexión real)."""
    called = False

    def boom(settings, mode):
        nonlocal called
        called = True
        raise AssertionError("no debería llegar aquí sin credenciales")

    monkeypatch.setattr(main_module, "_assemble_real_engine", boom)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        main_module._construct_real_engine(Settings(anthropic_api_key=None, openai_api_key=None), "agent")
    assert called is False


def test_construct_real_engine_delegates_when_credentials_present(monkeypatch):
    monkeypatch.setattr(main_module, "_assemble_real_engine", lambda settings, mode: f"motor-{mode}")

    settings = Settings(anthropic_api_key="sk-ant-x", openai_api_key="sk-oai-x")
    assert main_module._construct_real_engine(settings, "rag") == "motor-rag"


async def test_agent_mode_without_credentials_fails_at_startup_not_silently(monkeypatch):
    """Regresión de extremo a extremo del hallazgo B1: antes, ENGINE_MODE=agent sin
    claves arrancaba, /health/ready daba 200 y cada POST devolvía 'error interno' en
    silencio. Ahora el lifespan debe romper AL ARRANCAR: el pod nunca llega a listo."""
    monkeypatch.delenv("USE_FAKE_ENGINE", raising=False)
    monkeypatch.setenv("ENGINE_MODE", "agent")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        app = create_app()
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            async with app.router.lifespan_context(app):
                raise AssertionError("el lifespan no debería completar sin credenciales")
    finally:
        get_settings.cache_clear()
