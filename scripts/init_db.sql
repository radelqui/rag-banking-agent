-- Lo ejecuta el DBA en el banco. Aquí, para el entorno local.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS accounts (
  customer_id TEXT PRIMARY KEY,
  balance NUMERIC(14,2) NOT NULL,
  currency CHAR(3) NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  annual_rate NUMERIC(5,2) NOT NULL
);
INSERT INTO accounts VALUES ('C123', 1520.75, 'EUR') ON CONFLICT DO NOTHING;
INSERT INTO products VALUES ('PROD-8849-X', 'Depósito Plus 12m', 3.25) ON CONFLICT DO NOTHING;

-- Tabla de vectores (LlamaIndex crea "data_<table>" pero la definimos explícita para el índice)
CREATE TABLE IF NOT EXISTS data_documentos_bancarios (
  id BIGSERIAL PRIMARY KEY,
  text TEXT NOT NULL,
  metadata_ JSONB,
  node_id TEXT,
  embedding vector(1536),
  text_search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', text)) STORED
);
-- Índice HNSW (búsqueda semántica) + GIN (búsqueda de texto exacto)
CREATE INDEX IF NOT EXISTS idx_docs_hnsw ON data_documentos_bancarios
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_docs_tsv ON data_documentos_bancarios USING gin (text_search_tsv);

-- Usuario de la API (lectura/escritura)
CREATE ROLE app_user LOGIN PASSWORD 'app_pw';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Usuario de la IA: SOLO LECTURA (principio de mínimo privilegio)
CREATE ROLE ai_readonly LOGIN PASSWORD 'ro_pw';
GRANT SELECT ON accounts, products, data_documentos_bancarios TO ai_readonly;
ALTER ROLE ai_readonly SET statement_timeout = '5s';
