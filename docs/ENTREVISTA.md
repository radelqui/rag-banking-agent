# Preparación entrevista — Python Developer + IA (Coforge / Santander)

Estructura para responder cualquier pregunta técnica: **Contexto → Qué haría → Por qué → Qué NO haría**. Habla de este repo como ejemplo real.

## Bloque 1 — Seguridad del agente
**1. ¿Cómo evitas que un usuario manipule al LLM y ejecute consultas destructivas?**
Defensa en capas: (a) el LLM nunca escribe SQL; solo invoca tools Python tipadas con consultas parametrizadas (`text("... :cid")`); (b) esas tools usan una conexión con un rol PostgreSQL de SOLO SELECT y `statement_timeout`; (c) guardrails de entrada filtran patrones de injection antes de gastar tokens; (d) la salida se enmascara (IBAN, DNI) antes de llegar al cliente; (e) contenedor non-root con filesystem read-only. Aunque el injection tuviera éxito, el daño máximo es un SELECT sobre tablas permitidas.

**2. ¿Quién gestiona los permisos de BD?**
El DBA crea los roles; DevOps los inyecta como Kubernetes Secret; yo decido en el código qué credencial usa cada componente: `APP_DATABASE_URL` para la API, `LLAMAINDEX_DATABASE_URL` (solo lectura) para todo lo que toca el LLM.

**3. ¿Prompt injection indirecta?**
El riesgo es que un PDF ingestado contenga "ignora tus instrucciones". Mitigación: mismo mínimo privilegio (las tools no pueden hacer daño), system prompt que delimita el contexto recuperado como datos no instrucciones, y logging de tool calls para auditoría.

## Bloque 2 — Latencia y streaming
**4. El LLM tarda 12 s. ¿Cómo evitas timeouts?**
Endpoint `async def` + `StreamingResponse` con `text/event-stream`. LlamaIndex con `streaming=True` da un async generator; cada token se envía como evento SSE. La conexión se mantiene viva y el usuario ve texto desde el primer segundo. `asyncio.wait_for` por token para detectar cuelgues; `X-Accel-Buffering: no` para que Nginx no bufferice.

**5. ¿SSE o WebSockets?**
SSE: unidireccional, HTTP normal, reconexión automática, atraviesa proxies corporativos sin fricción. WebSockets solo si hay que enviar del cliente al servidor durante la generación.

**6. ¿Cómo evitas que un despliegue corte streams en curso?**
`preStop: sleep 15` + `terminationGracePeriodSeconds: 60`: K8s deja de enrutar tráfico al pod antes de enviar SIGTERM y da tiempo a cerrar respuestas.

## Bloque 3 — Docker y Kubernetes
**7. Buenas prácticas del Dockerfile.**
Multi-stage (builder con compiladores, runtime limpio), `python:3.11-slim`, `useradd` + `USER appuser`, `.dockerignore`, `HEALTHCHECK`, versiones pinneadas, escaneo con trivy en CI.

**8. Requests/limits y probes para un servicio que carga índices en RAM.**
`requests.memory: 1Gi` garantiza el mínimo; `limits.memory: 3Gi` evita que una fuga tumbe el nodo (OOMKilled solo del pod). Tres probes: `startupProbe` (hasta 150 s para cargar índices sin que liveness mate el pod), `readinessProbe` (sin tráfico hasta estar listo), `livenessProbe` (reinicia si el proceso muere). Liveness debe ser barata: no toca BD ni LLM.

## Bloque 4 — PostgreSQL, vectores, RAG
**9. ¿Qué extensión y qué índice?**
`pgvector`; operador `<=>` para coseno. IVFFlat: rápido de construir, menor recall. HNSW: grafo multicapa, mejor recall y latencia, más RAM; es el estándar en producción. Parámetros: `m=16`, `ef_construction=64`, `ef_search` ajustable en consulta.

**10. Códigos exactos + preguntas conceptuales.**
Búsqueda híbrida: `hybrid_search=True` en `PGVectorStore` combina embedding con `tsvector`/GIN (BM25-like), fusiona resultados y opcionalmente reranking (cross-encoder) antes de mandar top-5 al LLM.

**11. ¿Cómo evitas alucinaciones?**
RAG con citas de fuente en metadata, `similarity_cutoff`, instrucción "si no está en el contexto, di que no lo sabes", evaluación offline con LlamaIndex `FaithfulnessEvaluator` sobre un set dorado.

## Bloque 5 — CI/CD y calidad
**12. Describe tu pipeline.**
PR → ruff (lint) → bandit (SAST) → pytest con cobertura mínima 85% → build imagen → trivy (CVE CRITICAL/HIGH bloquean) → deploy a `environment: production` con aprobación manual → `kubectl rollout status`. Los secretos nunca están en el repo; el pipeline los toma del entorno seguro del banco. Da igual si es Jenkins, GitLab CI o Azure DevOps: el concepto es idéntico.

## Preguntas de comportamiento probables
- "Cuéntame un bug difícil" → prepara uno real, con causa raíz y prevención.
- "¿Cómo trabajas con DBA/DevOps?" → contrato claro: yo pido roles y secretos con nombre y permisos definidos, ellos los crean.
- "¿Qué haces si el requisito no está claro?" → prototipo con FakeEngine y demo rápida.

## Frases que evitar
- "Eso lo hace el banco" → sustituir por "el banco asegura el perímetro; yo aseguro el código y el agente".
- "No sé" a secas → "No lo he usado en producción, pero el concepto es X y lo haría así".

## Bloque 6 — Lo que la primera versión tenía mal (y cómo se corrigió)
**13. ¿Quién decide de qué cliente es la consulta?**
Nunca el LLM. La identidad llega en una cabecera que rellena el API gateway del banco tras autenticar (OAuth2/AD). Sin cabecera, 401. Las tools se enlazan a ese cliente antes de entregarse al modelo: la función de saldo no admite parámetro de cliente. Así "dame el saldo del cliente C999" no puede consultar a otro. Es autorización, no solo autenticación.

**14. ¿Por qué el enmascarado token a token no sirve en streaming?**
Un IBAN llega partido en varios tokens y ninguna regex lo ve. `StreamMasker` acumula y solo emite en fin de frase o salto de línea, donde ningún IBAN/DNI/tarjeta/email puede quedar cortado; al terminar vacía lo retenido. Hay un test que parte un IBAN en cuatro tokens.

**15. ¿Cómo evitas que documentos del banco salgan a internet para calcular embeddings?**
Modelo y URL de pasarela son variables de entorno (`ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`). En el banco apuntan a su pasarela interna; el código no cambia. Igual que la BD: yo conozco los nombres, DevOps pone los valores.

**16. ¿Tu pipeline pasaba?**
La primera versión no: exigía 85% de cobertura y daba 71%. Los tests estaban verdes pero el CI habría bloqueado el primer deploy. Ahora 42 tests, 96%, y `make test` usa la misma puerta que el CI.
