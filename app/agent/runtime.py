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

import functools
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.tools import ToolError, bind_tools
from app.rag.prompts import AGENT_SYSTEM_PROMPT

log = logging.getLogger(__name__)

# H2 (verificador, PLAN-0001): LlamaIndex captura CUALQUIER excepción de una tool con
# `str(e)` y la reinyecta tal cual como resultado de la tool -al historial que ve el
# LLM y, de ahí, potencialmente a la respuesta que se transmite al cliente- (ver
# FunctionAgent._call_tool / QueryEngineTool.acall). Un tool_call con kwargs que la
# función no admite (p.ej. un customer_id que el LLM intente colar) revienta con un
# TypeError que expone el nombre interno de la función («bind_tools.<locals>.balance()
# got an unexpected keyword argument…»). Este mensaje NUNCA debe llegar al cliente.
_GENERIC_TOOL_ERROR = "No se pudo completar la operación solicitada."


def _safe_tool_call(name: str, fn):
    """Envuelve una tool: los `ToolError` de negocio (mensajes ya pensados para el
    usuario, p.ej. "producto no encontrado") pasan tal cual. Cualquier OTRA excepción
    -kwargs inesperados, error de BD, timeout, bug interno- se convierte en un mensaje
    genérico; el detalle completo va solo al log, nunca al historial del LLM ni al
    stream del cliente.
    """

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception:
            log.exception("error inesperado en la tool %s", name)
            raise ToolError(_GENERIC_TOOL_ERROR) from None

    return wrapped


class RagEngineLike(Protocol):
    """Mismo contrato que `app.rag.engine.QueryEngineLike` (evita el import cruzado)."""

    def astream(self, question: str, customer_id: str) -> AsyncIterator[str]: ...


def _function_tools(sql_engine: AsyncEngine, customer_id: str) -> list[Any]:
    """FunctionTool de LlamaIndex para las tools bancarias, ya enlazadas al cliente."""
    from llama_index.core.tools import FunctionTool

    fns = bind_tools(sql_engine, customer_id)
    return [
        FunctionTool.from_defaults(async_fn=_safe_tool_call(name, fn), name=name)
        for name, fn in fns.items()
    ]


def _rag_tool(rag_engine: RagEngineLike, customer_id: str) -> Any:
    """Tool de búsqueda documental para el agente.

    Si `rag_engine` expone un motor nativo de LlamaIndex (`LlamaIndexEngine._qe`, el
    RetrieverQueryEngine real construido en app.rag.engine), se consulta directamente
    (retrieval real, PLAN-0001). Si no (p.ej. FakeEngine en tests), se envuelve el
    mismo contrato `astream()`: incluso una fuente RAG de mentira queda accesible al
    agente con la misma interfaz pública. Ambos casos pasan por `_safe_tool_call`: un
    fallo de la BD vectorial o del embedder tampoco debe filtrar detalles internos.
    """
    from llama_index.core.tools import FunctionTool

    native_qe = getattr(rag_engine, "_qe", None)

    async def buscar_documentacion(pregunta: str) -> str:
        """Busca en la documentación bancaria interna sobre productos y políticas."""
        if native_qe is not None:
            return str(await native_qe.aquery(pregunta))
        return "".join([token async for token in rag_engine.astream(pregunta, customer_id)])

    return FunctionTool.from_defaults(
        async_fn=_safe_tool_call("buscar_documentacion", buscar_documentacion),
        name="buscar_documentacion",
    )


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
