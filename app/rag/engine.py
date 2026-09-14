"""Motor de consulta RAG con streaming. Lo pesado se crea una vez (lifespan)."""
from collections.abc import AsyncIterator
from typing import Protocol

from app.core.config import Settings


class QueryEngineLike(Protocol):
    def astream(self, question: str, customer_id: str) -> AsyncIterator[str]: ...


class LlamaIndexEngine:  # pragma: no cover - requiere BD + LLM reales (test de integración)
    def __init__(self, settings: Settings):
        from llama_index.core import Settings as LISettings
        from llama_index.core import VectorStoreIndex
        from llama_index.core.prompts import PromptTemplate
        from llama_index.core.query_engine import RetrieverQueryEngine
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.anthropic import Anthropic

        from app.rag.prompts import QA_TEMPLATE
        from app.rag.vector_store import build_vector_store

        # Proveedores por configuración: modelo y pasarela vienen del entorno (banco).
        LISettings.llm = Anthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
        )
        LISettings.embed_model = OpenAIEmbedding(
            model=settings.embed_model,
            api_key=settings.openai_api_key,
            api_base=settings.openai_base_url,
        )
        index = VectorStoreIndex.from_vector_store(build_vector_store(settings))
        retriever = index.as_retriever(
            vector_store_query_mode="hybrid",
            similarity_top_k=settings.similarity_top_k,
        )
        self._qe = RetrieverQueryEngine.from_args(
            retriever=retriever,
            streaming=True,
            text_qa_template=PromptTemplate(QA_TEMPLATE),  # contexto = datos, no instrucciones
        )

    async def astream(self, question: str, customer_id: str) -> AsyncIterator[str]:
        # customer_id se acepta por contrato; el RAG puro no lo usa. Lo usará el agente con
        # tools (PLAN-0001) para enlazar get_account_balance al cliente autenticado.
        response = await self._qe.aquery(question)
        async for token in response.async_response_gen():
            yield token


class FakeEngine:
    """Para tests y desarrollo local sin BD/LLM."""

    def __init__(self, tokens: list[str] | None = None, fail: bool = False):
        self.tokens = tokens or ["Hola", " mundo"]
        self.fail = fail
        self.calls: list[str] = []
        self.customers: list[str] = []

    async def astream(self, question: str, customer_id: str) -> AsyncIterator[str]:
        self.calls.append(question)
        self.customers.append(customer_id)
        if self.fail:
            raise RuntimeError("boom")
        for t in self.tokens:
            yield t
