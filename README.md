# rag-banking-agent

Microservicio **FastAPI + LlamaIndex + PostgreSQL/pgvector** que responde consultas sobre documentos bancarios con un modelo de frontera, en streaming (SSE), desplegado en Docker/Kubernetes con CI/CD.

```
Pasarela del banco (OAuth2/AD) ──X-Customer-Id──▶ FastAPI
                                                   │  identidad (401 si falta) + guardrails + validación
                                                   ▼
                                             LlamaIndex RetrieverQueryEngine
                                             ├── Retriever HÍBRIDO (pgvector HNSW + full-text)
                                             ├── Prompt: el contexto recuperado son DATOS, no instrucciones
                                             ├── Tools tipadas, enlazadas al cliente autenticado (SOLO LECTURA)  [PLAN-0001: conectar al agente]
                                             └── LLM vía pasarela del banco ──▶ tokens ──▶ StreamMasker (PII) ──▶ SSE
```

## Estructura
```
app/
  main.py            arranque, lifespan (carga el motor 1 vez)
  api/routes.py      /health/live, /health/ready, /consultar (SSE)
  core/config.py     Settings desde variables de entorno (0 secretos en código)
  core/db.py         2 engines: app (rw) y ai (solo lectura)
  rag/vector_store.py PGVectorStore híbrido + HNSW
  rag/engine.py      LlamaIndexEngine (real) y FakeEngine (tests/dev)
  rag/prompts.py     plantilla QA: contexto = datos, no instrucciones
  agent/tools.py     tools tipadas, SQL parametrizado, enlazadas al cliente autenticado
  security/          identity.py (cabecera de la pasarela), guardrails.py (injection), pii.py (StreamMasker)
tests/               42 tests unitarios/integración HTTP (sin BD ni LLM real), cobertura 96%
scripts/init_db.sql  extensión vector, tablas, índices, roles app_user / ai_readonly (lo ejecuta el DBA)
Dockerfile           multi-stage, slim, non-root
k8s/                 Deployment (requests/limits, 3 probes, readOnlyRootFilesystem), Service, HPA
.github/workflows    lint → SAST → tests (≥85%) → build → trivy → deploy (con aprobación)
ci/                  mismas etapas para Jenkins y Azure DevOps (el banco elige la herramienta)
```

## Arrancar
```bash
make install
make test                 # 42 passed, cobertura ≥85% (misma puerta que el CI)
make dev                  # API con FakeEngine, sin BD/LLM
curl -N -X POST localhost:8000/api/v1/consultar \
  -H 'content-type: application/json' -H 'X-Customer-Id: C123' \
  -d '{"pregunta":"¿Cuál es mi saldo?"}'

cp .env.example .env      # rellena claves y, en el banco, las URLs de pasarela
make up                   # Postgres+pgvector + API reales
python scripts/ingest.py ./data   # ingesta PDFs
```

## Lo que pone el banco (contrato)
El código conoce los **nombres**; los **valores** los inyecta el banco al arrancar el contenedor.

| Qué | Quién lo da | Dónde se consume |
|---|---|---|
| `APP_DATABASE_URL`, `LLAMAINDEX_DATABASE_URL` (rol solo SELECT) | DBA crea roles, DevOps crea el Secret | `core/config.py` |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` + claves (pasarela LLM interna) | Plataforma IA / SecOps | `rag/engine.py` |
| Cabecera de identidad `X-Customer-Id` tras OAuth2/AD | API gateway del banco | `security/identity.py` |
| Registry de imágenes, clúster, KUBECONFIG | DevOps | pipeline + `k8s/` |
| Herramienta de CI (GitHub Actions / Jenkins / Azure DevOps) | DevOps | `.github/workflows/` o `ci/` |

> Las credenciales que aparecen en `docker-compose.yml` e `init_db.sql` (`app_pw`, `ro_pw`, `postgres`) son de un entorno local de demo, sin ningún valor fuera de este repo. En el banco las inyecta el pipeline, como en la tabla de arriba.

## Seguridad del agente (defensa en capas)
1. Identidad de la pasarela, nunca del prompt: el LLM no puede elegir cliente (tools enlazadas).
2. Guardrails de entrada (injection) antes de gastar tokens.
3. Tools tipadas + SQL parametrizado + rol PostgreSQL de solo lectura con `statement_timeout`.
4. Contexto recuperado marcado como datos en el prompt.
5. Salida enmascarada con buffer (`StreamMasker`): un IBAN partido en tokens no se escapa.
6. Contenedor non-root, filesystem de solo lectura, sin capabilities.

## Pendiente (planes)
- PLAN-0001: conectar `build_llamaindex_tools` a un agente LlamaIndex real (requiere LLM; verificar con `make up`).
- PLAN-0003: validar en integración que el esquema de `init_db.sql` coincide con el que espera `PGVectorStore` híbrido.

## Formación
- `docs/FORMACION.md` — plan de estudio de 10 días con ejercicios sobre este repo
- `docs/ENTREVISTA.md` — preguntas y respuestas modelo del proceso Coforge/Santander
