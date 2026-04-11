.PHONY: infra up down logs backend frontend test test-unit test-integration lint pull-model

# ── Infrastructure ───────────────────────────────────────────────────────────
infra:
	docker compose up -d postgres elasticsearch jaeger

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Pull Ollama model (run after Ollama container is up)
pull-model:
	docker compose exec ollama ollama pull qwen2.5:3b-instruct

# ── Backend (local dev) ───────────────────────────────────────────────────────
install:
	pip install -r requirements.txt dist/qf-1.0.2-py3-none-any.whl

backend:
	python main.py

# ── Frontend ──────────────────────────────────────────────────────────────────
frontend:
	cd frontend && npm run dev

frontend-install:
	cd frontend && npm install

frontend-build:
	cd frontend && npm run build

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short -m "not slow"

test-e2e:
	pytest tests/e2e/ -v --tb=short

lint:
	python -m py_compile main.py src/**/*.py && echo "Syntax OK"

# ── Sample data ───────────────────────────────────────────────────────────────
seed-es:
	python scripts/seed_elasticsearch.py
