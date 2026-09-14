"""PGVectorStore sobre PostgreSQL + pgvector con búsqueda híbrida y HNSW."""
from urllib.parse import urlparse

from app.core.config import Settings


def parse_db_url(url: str) -> dict:
    u = urlparse(url)
    return {
        "user": u.username,
        "password": u.password,
        "host": u.hostname,
        "port": u.port or 5432,
        "database": (u.path or "/").lstrip("/"),
    }


def build_vector_store(settings: Settings):  # pragma: no cover - requiere llama_index + pgvector
    from llama_index.vector_stores.postgres import PGVectorStore

    p = parse_db_url(settings.llamaindex_database_url)
    return PGVectorStore.from_params(
        database=p["database"],
        host=p["host"],
        password=p["password"],
        port=p["port"],
        user=p["user"],  # usuario de SOLO LECTURA
        table_name=settings.vector_table,
        embed_dim=settings.embed_dim,
        hybrid_search=True,  # vector + full-text (BM25)
        text_search_config="spanish",
        use_jsonb=True,  # init_db.sql define metadata_ como JSONB
        perform_setup=False,  # el esquema lo crea el DBA (init_db.sql); ai_readonly no puede hacer DDL
        hnsw_kwargs={  # índice HNSW: estándar en producción
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )
