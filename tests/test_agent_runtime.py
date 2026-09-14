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

from llama_index.core.base.llms.types import ChatMessage, ChatResponse, LLMMetadata, MessageRole
from llama_index.core.llms.function_calling import FunctionCallingLLM
from llama_index.core.llms.llm import ToolSelection

from app.agent.runtime import AgentEngine, build_agent
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
