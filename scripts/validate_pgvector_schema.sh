#!/usr/bin/env bash
set -euo pipefail

FAIL=0
SQL="scripts/init_db.sql"
VS="app/rag/vector_store.py"
DC="docker-compose.yml"

ok()   { echo "[OK]   $1"; }
fail() { echo "[FALLO] $1"; FAIL=1; }

# 1) Tabla con las 6 columnas tipadas
grep -q 'id BIGSERIAL PRIMARY KEY'                              "$SQL" && ok "columna id BIGSERIAL"         || fail "falta id BIGSERIAL en $SQL"
grep -q 'text VARCHAR NOT NULL'                                  "$SQL" && ok "columna text VARCHAR"          || fail "falta text VARCHAR en $SQL"
grep -q 'metadata_ JSONB'                                       "$SQL" && ok "columna metadata_ JSONB"       || fail "falta metadata_ JSONB en $SQL"
grep -q 'node_id VARCHAR'                                        "$SQL" && ok "columna node_id"               || fail "falta node_id en $SQL"
grep -q 'embedding vector(1536)'                                 "$SQL" && ok "columna embedding vector"      || fail "falta embedding vector(1536) en $SQL"
grep -q "text_search_tsv tsvector GENERATED ALWAYS AS"           "$SQL" && ok "columna tsvector GENERATED"    || fail "falta text_search_tsv GENERATED en $SQL"

# 2) Tres índices con nombres de PGVectorStore
grep -q 'CREATE INDEX IF NOT EXISTS data_documentos_bancarios_embedding_idx' "$SQL" && ok "índice HNSW"   || fail "falta índice HNSW en $SQL"
grep -q 'CREATE INDEX IF NOT EXISTS documentos_bancarios_idx '               "$SQL" && ok "índice GIN"    || fail "falta índice GIN en $SQL"
grep -q 'CREATE INDEX IF NOT EXISTS documentos_bancarios_idx_1'              "$SQL" && ok "índice BTREE"  || fail "falta índice BTREE en $SQL"

# 3) Rol ai_readonly con SELECT y statement_timeout
grep -q 'CREATE ROLE ai_readonly'         "$SQL" && ok "rol ai_readonly creado"     || fail "falta CREATE ROLE ai_readonly en $SQL"
grep -q 'GRANT SELECT.*ai_readonly'       "$SQL" && ok "ai_readonly solo SELECT"    || fail "falta GRANT SELECT a ai_readonly en $SQL"
grep -q "statement_timeout.*=.*'5s'"      "$SQL" && ok "statement_timeout 5s"       || fail "falta statement_timeout en $SQL"

# 4) Cero contraseñas literales (PASSWORD solo seguido de :'var', nunca de 'cadena')
if grep -P "PASSWORD\s+'[^:]" "$SQL" >/dev/null 2>&1; then
  fail "contraseña literal detectada en $SQL"
else
  ok "cero contraseñas literales en SQL"
fi

# 5) Compose: env_file y variables interpoladas
grep -q 'env_file:'     "$DC" && ok "compose usa env_file"         || fail "falta env_file en $DC"
grep -q '${APP_PW}'     "$DC" && ok "compose interpola APP_PW"     || fail "falta \${APP_PW} en $DC"
grep -q '${RO_PW}'      "$DC" && ok "compose interpola RO_PW"      || fail "falta \${RO_PW} en $DC"

# 6) PGVectorStore: configuración híbrida sin DDL
grep -q 'perform_setup=False'             "$VS" && ok "perform_setup=False"          || fail "falta perform_setup=False en $VS"
grep -q 'hybrid_search=True'              "$VS" && ok "hybrid_search=True"           || fail "falta hybrid_search=True en $VS"
grep -q 'text_search_config="spanish"'    "$VS" && ok "text_search_config=spanish"   || fail "falta text_search_config=spanish en $VS"
grep -q 'use_jsonb=True'                  "$VS" && ok "use_jsonb=True"               || fail "falta use_jsonb=True en $VS"

if [ "$FAIL" -eq 0 ]; then
  echo "--- RESULTADO: todas las comprobaciones pasaron ---"
  exit 0
else
  echo "--- RESULTADO: hay fallos ---"
  exit 1
fi
