# ─────────────────────────────────────────────────────────────────────────────
#  AI-MSHM Backend  –  Developer Makefile
#
#  Usage:
#    make dev          Start full local stack (Docker)
#    make test         Run test suite
#    make seed         Seed demo data
#    make shell        Django shell
#    make migrate      Run migrations
#    make lint         Run ruff linter
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: help dev stop test test-cov seed migrate shell lint format clean logs

# ── Settings ──────────────────────────────────────────────────────────────────
COMPOSE     = docker compose
API_SERVICE = api
MANAGE      = python manage.py

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  AI-MSHM Backend — available commands:"
	@echo ""
	@echo "  make dev          Build and start full Docker stack"
	@echo "  make stop         Stop all Docker services"
	@echo "  make logs         Tail API logs"
	@echo ""
	@echo "  make migrate      Run database migrations"
	@echo "  make migrations   Make new migration files"
	@echo "  make seed         Seed demo users and data"
	@echo "  make superuser    Create a Django superuser"
	@echo "  make shell        Open Django shell"
	@echo ""
	@echo "  make test         Run full test suite"
	@echo "  make test-cov     Run tests with coverage report"
	@echo "  make test-auth    Run only auth tests"
	@echo "  make test-fast    Run tests excluding slow/integration"
	@echo ""
	@echo "  make lint         Run ruff linter"
	@echo "  make format       Auto-format with ruff"
	@echo "  make clean        Remove .pyc / __pycache__ / .pytest_cache"
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────
dev:
	$(COMPOSE) up -d --build
	@echo "✅  Stack running at http://localhost:8000"
	@echo "    Docs:  http://localhost:8000/api/docs/"
	@echo "    Admin: http://localhost:8000/admin/"

stop:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f $(API_SERVICE)

restart:
	$(COMPOSE) restart $(API_SERVICE)

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) migrate

migrations:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) makemigrations

seed:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) seed_demo
	@echo "✅  Demo data seeded"
	@echo "    patient@demo.com   / Demo1234!"
	@echo "    clinician@demo.com / Demo1234!"

seed-flush:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) seed_demo --flush
	@echo "✅  Flushed and re-seeded"

superuser:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) createsuperuser

# ── Shell ─────────────────────────────────────────────────────────────────────
shell:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) shell_plus 2>/dev/null || \
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) shell

# ── Static ────────────────────────────────────────────────────────────────────
static:
	$(COMPOSE) exec $(API_SERVICE) $(MANAGE) collectstatic --noinput

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	$(COMPOSE) exec $(API_SERVICE) pytest

test-cov:
	$(COMPOSE) exec $(API_SERVICE) pytest --cov=apps --cov=core --cov-report=html --cov-report=term-missing
	@echo "📊  Coverage report: htmlcov/index.html"

test-auth:
	$(COMPOSE) exec $(API_SERVICE) pytest apps/accounts/tests/ -v

test-onboarding:
	$(COMPOSE) exec $(API_SERVICE) pytest apps/onboarding/tests/ -v

test-notifications:
	$(COMPOSE) exec $(API_SERVICE) pytest apps/notifications/tests/ -v

test-settings:
	$(COMPOSE) exec $(API_SERVICE) pytest apps/settings_app/tests/ -v

test-fast:
	$(COMPOSE) exec $(API_SERVICE) pytest -m "not slow and not integration"

test-centers:
	$(COMPOSE) exec $(API_SERVICE) pytest apps/centers/tests/ -v

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check .

format:
	ruff format .
	ruff check . --fix

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@echo "🧹  Cleaned"
