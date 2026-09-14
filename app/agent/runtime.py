"""Agente LlamaIndex real (PLAN-0001): conecta `build_llamaindex_tools` a un
FunctionAgent con QueryEngineTool, en vez de dejarlas sin usar.

Reglas de oro (heredadas de app.agent.tools, no se repiten aquí):
1. El customer_id se resuelve ANTES de construir el agente (bind_tools), nunca lo
   elige el LLM: cada request autenticado construye su propio agente con las tools
   ya atadas a ESE cliente.
2. Este módulo no decide el LLM ni el motor RAG: los recibe inyectados. Quien arma
   la aplicación (lifespan de app.main) es responsable de pasar el LLM real
   (Anthropic vía la pasarela del banco, `Settings.llm_model`) y el motor RAG
   (`LlamaIndexEngine` real o `FakeEngine` en tests) — así este módulo se prueba
   con dobles, sin credenciales ni red.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.tools import bind_tools
from app.rag.prompts import AGENT_SYSTEM_PROMPT


class RagEngineLike(Protocol):
    """Mismo contrato que `app.rag.engine.QueryEngineLike` (evita el import cruzado)."""

    def astream(self, question: str, customer_id: str) -> AsyncIterator[str]: ...


def _function_tools(sql_engine: AsyncEngine, customer_id: str) -> list[Any]:
    """FunctionTool de LlamaIndex para las tools bancarias, ya enlazadas al cliente."""
    from llama_index.core.tools import FunctionTool

    fns = bind_tools(sql_engine, customer_id)
    return [FunctionTool.from_defaults(async_fn=fn, name=name) for name, fn in fns.items()]


def _rag_tool(rag_engine: RagEngineLike, customer_id: str) -> Any:
    """Tool de búsqueda documental para el agente.

    Si `rag_engine` expone un motor nativo de LlamaIndex (`LlamaIndexEngine._qe`, el
    RetrieverQueryEngine real construido en app.rag.engine), se envuelve con
    QueryEngineTool tal como pide PLAN-0001. Si no (p.ej. FakeEngine en tests), se
    envuelve el mismo contrato `astream()` en un FunctionTool: incluso una fuente RAG
    de mentira queda accesible al agente con la misma interfaz pública.
    """
    from llama_index.core.tools import FunctionTool, QueryEngineTool

    native_qe = getattr(rag_engine, "_qe", None)
    if native_qe is not None:
        return QueryEngineTool.from_defaults(
            query_engine=native_qe,
            name="buscar_documentacion",
            description="Busca en la documentación y políticas bancarias internas.",
        )

    async def buscar_documentacion(pregunta: str) -> str:
        """Busca en la documentación bancaria interna sobre productos y políticas."""
        return "".join([token async for token in rag_engine.astream(pregunta, customer_id)])

    return FunctionTool.from_defaults(async_fn=buscar_documentacion, name="buscar_documentacion")


def build_agent(sql_engine: AsyncEngine, rag_engine: RagEngineLike, customer_id: str, llm: Any):
    """Construye un FunctionAgent con las tools ya atadas a `customer_id`.

    `llm` debe ser un FunctionCallingLLM real (Anthropic vía la pasarela del banco en
    producción) o un doble de test que implemente ese contrato.
    """
    from llama_index.core.agent.workflow import FunctionAgent

    tools = [*_function_tools(sql_engine, customer_id), _rag_tool(rag_engine, customer_id)]
    return FunctionAgent(tools=tools, llm=llm, system_prompt=AGENT_SYSTEM_PROMPT)


class AgentEngine:
    """Adaptador que cumple el contrato QueryEngineLike (`astream(question, customer_id)`)
    para poder sustituir a `LlamaIndexEngine`/`FakeEngine` en `app.api.routes` sin tocar
    la capa HTTP: cada consulta arma un agente con tools atadas al cliente autenticado
    y transmite en streaming los deltas de la respuesta final del LLM.
    """

    def __init__(self, sql_engine: AsyncEngine, rag_engine: RagEngineLike, llm: Any):
        self._sql_engine = sql_engine
        self._rag_engine = rag_engine
        self._llm = llm

    async def astream(self, question: str, customer_id: str) -> AsyncIterator[str]:
        from llama_index.core.agent.workflow import AgentStream

        agent = build_agent(self._sql_engine, self._rag_engine, customer_id, self._llm)
        handler = agent.run(user_msg=question)
        async for event in handler.stream_events():
            if isinstance(event, AgentStream) and event.delta:
                yield event.delta
        await handler  # propaga excepciones de la ejecución del workflow
