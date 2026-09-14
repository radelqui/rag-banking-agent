"""Ingesta de documentos → chunks → embeddings → pgvector. Se ejecuta con el usuario app_user."""
import sys

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from app.core.config import get_settings
from app.rag.vector_store import build_vector_store

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "./data"
    s = get_settings()
    # Para ingestar usamos la URL con permisos de escritura
    s.llamaindex_database_url = s.app_database_url
    docs = SimpleDirectoryReader(folder).load_data()
    ctx = StorageContext.from_defaults(vector_store=build_vector_store(s))
    VectorStoreIndex.from_documents(
        docs, storage_context=ctx,
        transformations=[SentenceSplitter(chunk_size=512, chunk_overlap=64)],
        show_progress=True,
    )
    print(f"Ingestados {len(docs)} documentos")
