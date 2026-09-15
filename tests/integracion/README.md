# Test de integración PLAN-0003 — hybrid search con `ai_readonly`

Objetivo: demostrar contra un Postgres+pgvector real que el esquema de
`scripts/init_db.sql` coincide con lo que espera `PGVectorStore` y que el
usuario de solo lectura `ai_readonly` puede ejecutar hybrid search (vector +
texto) usando los índices ya creados, sin disparar ningún DDL
(`perform_setup=False`).

> **Corrección a la petición del lead (§11):** el mensaje que originó este
> README cita el índice `idx_docs_hnsw`. Ese nombre es el que tenía el SQL
> ANTES del fix de PLAN-0003. Tras `b6fa6ab` los índices se renombraron a los
> nombres que genera la propia librería, para que su
> `CREATE INDEX IF NOT EXISTS` no duplique nada. Además, el fix de B2/B3
> (llama-index-llms-anthropic sin pin de `anthropic`, `llm_model` desconocido)
> obligó a subir `llama-index-vector-stores-postgres` de 0.4.1 a 0.9.0 —esa
> versión añade SIEMPRE un tercer índice (`ref_doc_id` para borrado por
> documento) que no existía antes. Los tres índices vigentes ahora:
> - `data_documentos_bancarios_embedding_idx` (HNSW, vector)
> - `documentos_bancarios_idx` (GIN, tsvector)
> - `documentos_bancarios_idx_1` (BTREE, `metadata_->>'ref_doc_id'`)
>
> El comando de abajo usa los nombres correctos (post-fix, post-upgrade).

## Precondición

`.env` con `POSTGRES_PASSWORD`, `APP_PW` y `RO_PW` rellenas (copiar
`.env.example` → `.env`; nunca commitear `.env`, ya está en `.gitignore`).
Desde `beecb06`/tras el fix de GitGuardian, ninguna contraseña vive literal
en `docker-compose.yml` ni en `scripts/init_db.sql`: las lee el contenedor
de `.env` (`env_file:` en el compose) y `init_db.sql` las captura con
`\set ... \`echo "$APP_PW"\`` + `:'var'` (interpolación segura de psql).

Levantar los servicios definidos en `docker-compose.yml` (raíz del repo,
`rag-banking-agent`):

```bash
docker compose up -d --build db
docker compose exec -T db pg_isready -U postgres
```

`db` ejecuta `scripts/init_db.sql` automáticamente vía
`docker-entrypoint-initdb.d` (ver `docker-compose.yml`), lo que crea:
- las tablas `accounts`, `products`, `data_documentos_bancarios`,
- los roles `app_user` (lectura/escritura) y `ai_readonly` (solo `SELECT`,
  `statement_timeout=5s`),
- los índices HNSW + GIN con los nombres de PGVectorStore.

**Para el CI**: exportar `POSTGRES_PASSWORD`, `APP_PW`, `RO_PW` como GitHub
Actions secrets (no hace falta que sean el mismo valor que en local; solo
tienen que existir y coincidir entre el paso que hace `docker compose up`
y el que después se conecta como `ai_readonly`/`app_user`) antes de
`docker compose up -d --build`. Sin ellas, `init_db.sql` crea los roles
con contraseña vacía y el paso de abajo fallará igual (evidencia visible,
no un fallo silencioso).

## Comando exacto que debe correr el CI (paso nuevo en `01-git-cicd`)

```bash
docker compose exec -T db psql -U ai_readonly -d banco -v ON_ERROR_STOP=1 <<'SQL'
-- 1) ai_readonly solo puede SELECT: cualquier intento de escritura debe fallar.
--    (No se ejecuta aquí un INSERT/UPDATE real; se confirma con \dp más abajo.)

-- 2) Sembrar un doc mínimo con app_user sería lo ideal, pero ai_readonly no
--    puede insertar. Este paso asume que ingest.py (ejecutado antes, con
--    app_user) ya dejó al menos una fila. Fallback: si la tabla está vacía,
--    el CI debe correr antes:
--      docker compose exec -T db psql -U app_user -d banco -c \
--        "INSERT INTO data_documentos_bancarios (text, metadata_) VALUES \
--         ('Depósito Plus 12m: producto a 12 meses con tipo fijo del 3,25% TAE.', '{}');"

-- 3) Hybrid search real: vector (ANN sobre HNSW) + texto (GIN/tsvector),
--    igual al modo 'hybrid' que usa index.as_retriever() en app/rag/engine.py.
--    Se sustituye el embedding real por un vector de ceros: aquí solo se
--    valida que el plan usa los índices y que el rol puede ejecutar la
--    consulta, no la calidad semántica del resultado (eso lo cubre el RAG
--    end-to-end, fuera de este test).
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, text, ts_rank(text_search_tsv, plainto_tsquery('spanish', 'depósito')) AS rank
FROM data_documentos_bancarios
WHERE text_search_tsv @@ plainto_tsquery('spanish', 'depósito')
ORDER BY embedding <=> (SELECT array_fill(0, ARRAY[1536])::vector)
LIMIT 5;
SQL
```

### Qué debe verificar el CI en la salida de ese `EXPLAIN`

1. **Exit code 0** — si `ai_readonly` no tuviera `SELECT` sobre
   `data_documentos_bancarios`, `psql` devuelve error de permisos y el `EXPLAIN`
   nunca corre → falla el paso (gracias a `ON_ERROR_STOP=1`).
2. El plan debe mencionar **al menos uno de los índices de búsqueda**
   (confirma que no se hace *seq scan* completo):
   - `documentos_bancarios_idx` (Bitmap Index Scan, filtro GIN por
     `text_search_tsv @@ ...`), y/o
   - `data_documentos_bancarios_embedding_idx` (Index Scan, `<=>` sobre HNSW).
   Grep sugerido: `grep -E "documentos_bancarios_idx|data_documentos_bancarios_embedding_idx"`.
   (`documentos_bancarios_idx_1`, el BTREE de `ref_doc_id`, no participa en esta
   consulta — solo lo usa `PGVectorStore.delete()`; basta con que exista.)
3. **Ningún DDL en el log de la app** al arrancar el contenedor `api`
   (confirma `perform_setup=False`):
   ```bash
   docker compose logs api | grep -i "PG Setup" && exit 1 || echo "OK: sin DDL en arranque"
   ```

### Verificación de privilegio mínimo (opcional pero recomendado)

```bash
docker compose exec -T db psql -U ai_readonly -d banco -c \
  "INSERT INTO data_documentos_bancarios (text) VALUES ('no debería poder');" \
  && exit 1 || echo "OK: ai_readonly no puede escribir (permission denied esperado)"
```

## Resultado esperado

- `EXPLAIN` corre sin error de permisos.
- El plan usa al menos uno de los dos índices (no seq scan).
- El intento de `INSERT` con `ai_readonly` falla con `permission denied`.
- Sin líneas `PG Setup:` en los logs de `api` (no hay DDL en caliente).

Si las tres condiciones se cumplen, PLAN-0003 queda demostrado en vivo y se
puede cerrar como **verificado** (no solo "propuesto" contra el modelo
estático de la librería, que es lo único que esta máquina pudo probar sin
Docker).
