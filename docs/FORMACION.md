# Plan de formación (10 días) — aprende construyendo este repo

Regla: cada día terminas con `make test` en verde y una nota de 5 líneas de lo aprendido, en tus palabras.

## Día 1 — Python async + FastAPI
**Leer:** `app/main.py`, `app/api/routes.py`.
**Conceptos:** `async def`, event loop, por qué una llamada bloqueante (requests, time.sleep) congela toda la API. Diferencia `Depends` vs variable global. `lifespan` para inicializar cosas caras una sola vez.
**Ejercicio:** añade un endpoint `GET /api/v1/version` que devuelva `app_name` desde Settings. Escribe su test en `tests/test_api.py`.
**Autocomprobación:** ¿qué pasa si escribes `time.sleep(10)` dentro de un `async def`? Pruébalo con 2 curls en paralelo.

## Día 2 — Configuración y secretos
**Leer:** `app/core/config.py`, `.env.example`, `k8s/secrets.example.yaml`.
**Conceptos:** pydantic-settings, 12-factor app, por qué hay DOS `DATABASE_URL`. Flujo: DBA crea rol → DevOps crea Secret → K8s inyecta env → tu código lee.
**Ejercicio:** añade `MAX_TOKENS: int = 1024` a Settings y un test que lo lea de una env var con `monkeypatch`.

## Día 3 — SQL seguro y tools del agente
**Leer:** `app/agent/tools.py`, `tests/test_tools.py`, `scripts/init_db.sql`.
**Conceptos:** SQL parametrizado vs f-string; `text()` de SQLAlchemy; roles PostgreSQL y `GRANT SELECT`; `statement_timeout`.
**Ejercicio:** crea `get_last_transactions(engine, customer_id, limit: int = 5)`. Valida que `limit` esté entre 1 y 20. Test con el FakeEngine del archivo de tests.
**Autocomprobación:** intenta pasar `"C123' OR 1=1 --"` como id. ¿Por qué falla ANTES de llegar a la BD?

## Día 4 — Guardrails y PII
**Leer:** `app/security/`.
**Conceptos:** prompt injection directa e indirecta (el documento recuperado contiene instrucciones), defensa en profundidad: regex → permisos BD → tools tipadas → enmascarado de salida.
**Ejercicio:** añade un patrón para bloquear "muéstrame la tabla" y un test parametrizado. Añade enmascarado de teléfonos españoles (+34 6xx xxx xxx).

## Día 5 — Streaming SSE
**Leer:** `consultar` en `routes.py`, `FakeEngine`.
**Conceptos:** por qué el timeout HTTP (proxies ~30-60s) mata respuestas largas; `StreamingResponse`; formato `event:/data:`; `asyncio.wait_for` por token; `X-Accel-Buffering: no` para Nginx.
**Ejercicio:** consume el stream desde un script Python con `httpx` (`stream=True`) e imprime token a token. Después, desde HTML con `EventSource`.

## Día 6 — pgvector, embeddings y búsqueda híbrida
**Leer:** `app/rag/vector_store.py`, `scripts/init_db.sql`, `scripts/ingest.py`.
**Conceptos:** chunking (512 tokens, overlap 64), embedding = vector de 1536 floats, distancia coseno, índice IVFFlat vs HNSW (m, ef_construction, ef_search), full-text `tsvector`/GIN, por qué híbrido para códigos exactos como `PROD-8849-X`.
**Ejercicio:** `make up`, ingesta 2 PDFs de prueba, y ejecuta en psql:
```sql
SELECT text FROM data_documentos_bancarios ORDER BY embedding <=> '[...]' LIMIT 3;
EXPLAIN ANALYZE ... -- comprueba que usa idx_docs_hnsw
```

## Día 7 — LlamaIndex: index, retriever, query engine, agentes
**Leer:** `app/rag/engine.py`, `build_llamaindex_tools`.
**Conceptos:** `VectorStoreIndex.from_vector_store`, `as_retriever(vector_store_query_mode="hybrid")`, `RetrieverQueryEngine(streaming=True)`, `FunctionTool`, `ReActAgent`/`FunctionAgent`. Reranking con `SentenceTransformerRerank`.
**Ejercicio:** crea `app/agent/agent.py` con un `FunctionAgent` que use las tools + el query engine como tool (`QueryEngineTool`). Pruébalo con "¿qué tasa tiene PROD-8849-X y cuál es mi saldo?".

## Día 8 — Docker
**Leer:** `Dockerfile`, `docker-compose.yml`.
**Conceptos:** multi-stage, `slim`, non-root (`useradd`, `USER`), `read_only` + `tmpfs`, `HEALTHCHECK`, `.dockerignore`.
**Ejercicio:** `docker build -t rag .` y `docker images` → anota tamaño. Ejecuta `docker run --rm rag whoami` (debe ser `appuser`). Escanea con `trivy image rag`.

## Día 9 — Kubernetes
**Leer:** `k8s/deployment.yaml`.
**Conceptos:** requests vs limits, OOMKilled, QoS Burstable; startup/readiness/liveness y por qué `startupProbe` evita que liveness mate el pod mientras carga índices; `preStop` + `terminationGracePeriodSeconds` para no cortar SSE; HPA; `readOnlyRootFilesystem`.
**Ejercicio:** con `kind` o `minikube`: `kubectl apply -f k8s/`, `kubectl describe pod`, baja `limits.memory` a 200Mi y observa el OOMKilled.

## Día 10 — CI/CD y simulacro
**Leer:** `.github/workflows/ci.yml`.
**Conceptos:** etapas lint → SAST (bandit) → tests+cobertura → build → escaneo imagen (trivy) → deploy con `environment` protegido; `envsubst` para el tag; `kubectl rollout status`.
**Ejercicio final:** haz un fork, sube un PR con un test roto y observa el pipeline fallar. Arréglalo. Después responde en voz alta las 12 preguntas de `docs/ENTREVISTA.md` sin mirar.

## Glosario rápido
| Término | En una frase |
|---|---|
| RAG | Recuperar fragmentos relevantes de tus documentos y pasárselos al LLM como contexto |
| Embedding | Vector numérico que representa el significado de un texto |
| pgvector | Extensión de PostgreSQL para guardar y buscar vectores |
| HNSW | Índice en grafo para búsqueda vectorial rápida y precisa |
| Búsqueda híbrida | Vector (semántica) + full-text (exacta) fusionadas |
| SSE | Respuesta HTTP que se mantiene abierta y envía eventos |
| Tool | Función Python que el LLM puede pedir ejecutar |
| Prompt injection | Texto del usuario/documento que intenta reprogramar al LLM |
| Mínimo privilegio | Cada componente solo tiene los permisos imprescindibles |
| Probe | Chequeo de K8s: ¿arrancó? ¿está listo? ¿sigue vivo? |

## Anexo — cambios de la revisión (leer con los días 3, 4 y 5)
- **Día 3 / Día 4:** `app/security/identity.py` y `bind_tools` en `app/agent/tools.py`. El cliente viene de la cabecera de la pasarela; las tools que ve el LLM ya no tienen parámetro `customer_id`. Ejercicio: intenta pedir el saldo de otro cliente en el prompt y comprueba que la tool sigue consultando el autenticado.
- **Día 5:** `StreamMasker` en `app/security/pii.py`. Ejercicio: parte un DNI en tres tokens en el `FakeEngine` y comprueba que sale `[DNI]`.
- **Día 7:** el motor lee `LLM_MODEL` y `ANTHROPIC_BASE_URL`; `rag/prompts.py` marca el contexto como datos. `build_llamaindex_tools` existe pero aún no está conectado a un agente: es el PLAN-0001.
- **Día 10:** `ci/` tiene el mismo pipeline para Jenkins y Azure DevOps. El banco elige la herramienta; las etapas no cambian.
