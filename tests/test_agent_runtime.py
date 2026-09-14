"""Prueba el agente real (PLAN-0001): FunctionAgent + tools bancarias + RAG.

No hay credenciales de Anthropic en este entorno, así que el LLM se sustituye por un
doble MÍNIMO de `FunctionCallingLLM` (ScriptedFunctionCallingLLM) que implementa el
mismo contrato que usa `FunctionAgent.take_step` (`astream_chat_with_tools` +
`get_tool_calls_from_response`). Esto ejecuta el workflow REAL de LlamaIndex —
selección de tool, ejecución, segundo turno con el resultado— no una versión mockeada
del agente. Verificar con la Anthropic real (ANTHROPIC_API_KEY) queda pendiente de que
el banco inyecte el secreto; ver README/CLAUDE.md de 04-agentes.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from llama_index.core.base.llms.types import ChatMessage, ChatResponse, LLMMetadata, MessageRole
from llama_index.core.llms.function_calling import FunctionCallingLLM
from llama_index.core.llms.llm import ToolSelection

from app.agent.runtime import _GENERIC_TOOL_ERROR, AgentEngine, build_agent
from app.agent.tools import ToolError
from app.rag.engine import FakeEngine


class FakeSqlEngine:
    """Motor SQL de solo lectura falso: misma forma que el AsyncEngine real."""

    def __init__(self, row=("100.50", "EUR")):
        self.row = row
        self.executed = []

    @asynccontextmanager
    async def connect(self):
        conn = MagicMock()

        async def execute(stmt, params):
            self.executed.append((str(stmt), params))
            res = MagicMock()
            res.first.return_value = self.row
            return res

        conn.execute = AsyncMock(side_effect=execute)
        yield conn


class ScriptedFunctionCallingLLM(FunctionCallingLLM):
    """Doble de FunctionCallingLLM: mientras el historial no tenga el resultado de la
    tool, pide `get_account_balance`; en cuanto lo tiene (rol "tool" en chat_history),
    devuelve el texto final. Decide por el HISTORIAL (no por un contador propio) para
    que cada request/cliente sea independiente, tal como en el agente real. Ejercita el
    bucle real de FunctionAgent.take_step sin red ni credenciales.
    """

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(is_function_calling_model=True, is_chat_model=True, model_name="fake-scripted")

    # --- métodos abstractos de LLM que este doble no necesita ejercitar ---
    def chat(self, messages, **kwargs):  # pragma: no cover - no usado por el workflow
        raise NotImplementedError

    def stream_chat(self, messages, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def complete(self, prompt, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def stream_complete(self, prompt, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def achat(self, messages, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def astream_chat(self, messages, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def acomplete(self, prompt, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def astream_complete(self, prompt, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def _prepare_chat_with_tools(self, tools, **kwargs):  # pragma: no cover
        raise NotImplementedError

    # --- lo que sí usa FunctionAgent.take_step ---
    def get_tool_calls_from_response(self, response, error_on_no_tool_call=True, **kwargs):
        return response.additional_kwargs.get("tool_selections", [])

    async def astream_chat_with_tools(
        self,
        tools,
        user_msg=None,
        chat_history=None,
        verbose=False,
        allow_parallel_tool_calls=False,
        **kwargs,
    ):
        tool_ya_respondio = any(m.role == "tool" for m in (chat_history or []))
        if tool_ya_respondio:
            message = ChatMessage(role=MessageRole.ASSISTANT, content="Su saldo es 100.5 EUR.")
            response = ChatResponse(
                message=message,
                delta="Su saldo es 100.5 EUR.",
                additional_kwargs={"tool_selections": []},
            )
        else:
            selections = [ToolSelection(tool_id="1", tool_name="get_account_balance", tool_kwargs={})]
            message = ChatMessage(role=MessageRole.ASSISTANT, content="")
            response = ChatResponse(
                message=message, delta="", additional_kwargs={"tool_selections": selections}
            )

        async def gen():
            yield response

        return gen()


def test_build_agent_expone_tools_bancarias_y_rag():
    sql_engine = FakeSqlEngine()
    rag_engine = FakeEngine()
    agent = build_agent(sql_engine, rag_engine, "C123", llm=ScriptedFunctionCallingLLM())
    names = {t.metadata.name for t in agent.tools}
    assert names == {"get_account_balance", "get_product_info", "buscar_documentacion"}


async def test_rag_tool_fallback_usa_function_tool_sobre_fake_engine():
    """FakeEngine no tiene `_qe` nativo de LlamaIndex: debe caer al FunctionTool que
    envuelve `astream()`, no reventar buscando un QueryEngine real."""
    sql_engine = FakeSqlEngine()
    rag_engine = FakeEngine(tokens=["Política ", "de privacidad."])
    agent = build_agent(sql_engine, rag_engine, "C123", llm=ScriptedFunctionCallingLLM())
    rag_tool = next(t for t in agent.tools if t.metadata.name == "buscar_documentacion")
    out = await rag_tool.async_fn(pregunta="¿cuál es la política?")
    assert out == "Política de privacidad."
    assert rag_engine.customers == ["C123"]  # el tool ató el cliente, el LLM nunca lo pasó


async def test_agent_engine_ejecuta_tool_atada_al_cliente_y_transmite_respuesta():
    sql_engine = FakeSqlEngine(row=("100.50", "EUR"))
    rag_engine = FakeEngine()
    engine = AgentEngine(sql_engine, rag_engine, llm=ScriptedFunctionCallingLLM())

    tokens = [t async for t in engine.astream("¿cuál es mi saldo?", "C123")]

    assert "".join(tokens) == "Su saldo es 100.5 EUR."
    # la tool ejecutó SQL parametrizado con el customer_id correcto, nunca elegido por el LLM
    assert sql_engine.executed[0][1] == {"cid": "C123"}


async def test_agent_engine_aisla_clientes_distintos():
    """Cada llamada a astream() construye tools nuevas atadas a SU customer_id: dos
    clientes en la misma instancia de AgentEngine nunca comparten identidad."""
    sql_engine = FakeSqlEngine(row=("7.00", "EUR"))
    rag_engine = FakeEngine()
    engine = AgentEngine(sql_engine, rag_engine, llm=ScriptedFunctionCallingLLM())

    await AsyncEngineDrain(engine.astream("saldo", "C1"))
    await AsyncEngineDrain(engine.astream("saldo", "C2"))

    assert [params for _, params in sql_engine.executed] == [{"cid": "C1"}, {"cid": "C2"}]


async def AsyncEngineDrain(agen):
    return [t async for t in agen]


# --- H2/H3 (veredicto del verificador sobre c1afb6d): un tool_call con kwargs que la
# función no admite no debe filtrar nombres internos («bind_tools.<locals>.balance…»)
# ni permitir que se cuele un customer_id distinto del atado a la tool. Las tres
# variantes que probó el verificador, reproducidas literalmente. ---


async def test_tool_kwargs_con_customer_id_ajeno_no_filtra_nombres_ni_ejecuta_sql():
    """Variante 1: tool_kwargs de `get_account_balance` con un customer_id (C999)
    que la función no admite."""
    sql_engine = FakeSqlEngine(row=("100.50", "EUR"))
    agent = build_agent(sql_engine, FakeEngine(), "C123", llm=ScriptedFunctionCallingLLM())
    balance_tool = next(t for t in agent.tools if t.metadata.name == "get_account_balance")

    with pytest.raises(ToolError) as exc:
        await balance_tool.acall(customer_id="C999")

    mensaje = str(exc.value)
    assert mensaje == _GENERIC_TOOL_ERROR
    assert "bind_tools" not in mensaje
    assert "<locals>" not in mensaje
    assert "balance" not in mensaje
    assert sql_engine.executed == []  # ni con C123 ni con C999: la tool nunca llegó a la BD


async def test_inyeccion_sql_en_product_code_no_ejecuta_nada_contra_la_bd():
    """Variante 2: inyección SQL en el argumento `product_code` de `get_product_info`."""
    sql_engine = FakeSqlEngine(row=None)
    agent = build_agent(sql_engine, FakeEngine(), "C123", llm=ScriptedFunctionCallingLLM())
    product_tool = next(t for t in agent.tools if t.metadata.name == "get_product_info")

    with pytest.raises(ToolError, match="inválido"):
        await product_tool.acall(product_code="X'; DROP TABLE accounts;--")

    assert sql_engine.executed == []  # la validación de _validate_id/product rechaza antes de tocar la BD


async def test_tool_rag_con_customer_id_ajeno_no_filtra_nombres_ni_consulta_por_otro_cliente():
    """Variante 3: tool_kwargs de `buscar_documentacion` con un customer_id (C999)
    que la función no admite — no debe consultar el RAG en nombre de otro cliente."""
    rag_engine = FakeEngine(tokens=["dato confidencial de C123"])
    agent = build_agent(FakeSqlEngine(), rag_engine, "C123", llm=ScriptedFunctionCallingLLM())
    rag_tool = next(t for t in agent.tools if t.metadata.name == "buscar_documentacion")

    with pytest.raises(ToolError) as exc:
        await rag_tool.acall(pregunta="dato", customer_id="C999")

    mensaje = str(exc.value)
    assert mensaje == _GENERIC_TOOL_ERROR
    assert "runtime" not in mensaje
    assert "<locals>" not in mensaje
    assert "buscar_documentacion" not in mensaje
    assert rag_engine.customers == []  # astream() nunca se llegó a invocar, ni con C123 ni con C999


class HostileFunctionCallingLLM(ScriptedFunctionCallingLLM):
    """Como ScriptedFunctionCallingLLM, pero en el primer turno intenta colar un
    customer_id ajeno en tool_kwargs (variante 1 del verificador) y, en el segundo,
    repite tal cual lo que "vio" en el resultado de la tool — el peor caso: un LLM
    que parafrasea/cita el contenido del error al usuario. Prueba de extremo a
    extremo (vía AgentEngine.astream, lo que de verdad llega al cliente) de que ni
    así se filtran nombres internos."""

    async def astream_chat_with_tools(
        self,
        tools,
        user_msg=None,
        chat_history=None,
        verbose=False,
        allow_parallel_tool_calls=False,
        **kwargs,
    ):
        tool_ya_respondio = any(m.role == "tool" for m in (chat_history or []))
        if tool_ya_respondio:
            ultimo_tool_msg = next(m for m in reversed(chat_history) if m.role == "tool")
            texto = ultimo_tool_msg.content or ""
            message = ChatMessage(role=MessageRole.ASSISTANT, content=texto)
            response = ChatResponse(message=message, delta=texto, additional_kwargs={"tool_selections": []})
        else:
            selections = [
                ToolSelection(
                    tool_id="1",
                    tool_name="get_account_balance",
                    tool_kwargs={"customer_id": "C999"},
                )
            ]
            message = ChatMessage(role=MessageRole.ASSISTANT, content="")
            response = ChatResponse(
                message=message, delta="", additional_kwargs={"tool_selections": selections}
            )

        async def gen():
            yield response

        return gen()


async def test_agent_engine_no_filtra_nombres_internos_ni_con_llm_hostil_de_extremo_a_extremo():
    """Aunque el LLM intente colar un customer_id ajeno Y luego repita al pie de la
    letra lo que la tool devolvió, lo que llega al stream del cliente (lo que
    consume app.api.routes) es el mensaje genérico, nunca el TypeError interno."""
    sql_engine = FakeSqlEngine(row=("100.50", "EUR"))
    engine = AgentEngine(sql_engine, FakeEngine(), llm=HostileFunctionCallingLLM())

    tokens = [t async for t in engine.astream("dame el saldo de otro cliente", "C123")]

    respuesta = "".join(tokens)
    assert respuesta == _GENERIC_TOOL_ERROR
    assert "bind_tools" not in respuesta
    assert "<locals>" not in respuesta
    assert sql_engine.executed == []  # el intento con C999 nunca tocó la BD
