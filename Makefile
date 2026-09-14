.PHONY: install test lint run dev up down
install: ; pip install -r requirements-dev.txt
test:    ; pytest --cov=app --cov-fail-under=85
lint:    ; ruff check . && bandit -r app -ll
dev:     ; USE_FAKE_ENGINE=1 uvicorn app.main:app --reload
run:     ; uvicorn app.main:app --host 0.0.0.0 --port 8000
up:      ; docker compose up --build
down:    ; docker compose down -v
