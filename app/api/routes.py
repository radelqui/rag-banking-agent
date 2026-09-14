import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import HealthResponse, QueryRequest
from app.core.config import Settings, get_settings
from app.security.guardrails import check_prompt
from app.security.identity import get_customer_id
from app.security.pii import StreamMasker

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def get_engine(request: Request):
    return request.app.state.engine


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="alive")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(request: Request) -> HealthResponse:
    if getattr(request.app.state, "engine", None) is None:
        raise HTTPException(status_code=503, detail="engine not ready")
    return HealthResponse(status="ready")


def sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/consultar")
async def consultar(
    body: QueryRequest,
    customer_id: str = Depends(get_customer_id),  # identidad: pasarela del banco, no el prompt
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    guard = check_prompt(body.pregunta)
    if not guard.allowed:
        log.warning("prompt bloqueado: %s", guard.reason)
        raise HTTPException(status_code=400, detail="Consulta no permitida")

    async def stream():
        masker = StreamMasker()
        try:
            gen = engine.astream(guard.sanitized, customer_id)
            while True:
                try:
                    token = await asyncio.wait_for(gen.__anext__(), settings.llm_timeout_seconds)
                except StopAsyncIteration:
                    break
                safe = masker.feed(token)
                if safe:
                    yield sse("token", safe)
            tail = masker.flush()
            if tail:
                yield sse("token", tail)
            yield sse("done", {"ok": True})
        except TimeoutError:
            yield sse("error", {"detail": "timeout del modelo"})
        except Exception:  # noqa: BLE001
            log.exception("error en streaming")
            yield sse("error", {"detail": "error interno"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
