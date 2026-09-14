# ---------- Etapa 1: builder ----------
FROM python:3.11-slim AS builder
WORKDIR /build
# apt-get upgrade: la imagen base python:3.11-slim no siempre trae los últimos parches de seguridad
# de Debian (gzip/libpcre2/libsqlite3/perl-base...); Trivy los bloquea en el pipeline si no se actualizan.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Etapa 2: runtime ----------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/install/bin:$PATH" PYTHONPATH=/install/lib/python3.11/site-packages
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
# pip/setuptools/wheel del sistema (no de requirements.txt) traían CVE: jaraco.context 5.3.0 (CVE-2026-23949)
# vendorizado dentro de setuptools, y wheel 0.45.1 (CVE-2026-24049). Es la imagen que Trivy escanea de verdad.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
# Usuario sin privilegios
RUN useradd --system --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder /install /install
COPY --chown=appuser:appuser app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health/live')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
