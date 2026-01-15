.PHONY: up down logs test test-docker clean help dev

# Default port (reads from .env or defaults to 8000)
PORT ?= 8000

# Start the stack with Docker Compose (production mode with workers)
up:
	docker compose build --no-cache
	UVICORN_CMD="--workers 2" docker compose up -d
	@echo ""
	@echo "🚀 API is running at: http://localhost:$(PORT)"
	@echo ""
	@echo "Endpoints:"
	@echo "  Health:   http://localhost:$(PORT)/health/live"
	@echo "  Ready:    http://localhost:$(PORT)/health/ready"
	@echo "  Webhook:  http://localhost:$(PORT)/webhook"
	@echo "  Messages: http://localhost:$(PORT)/messages"
	@echo "  Stats:    http://localhost:$(PORT)/stats"
	@echo "  Metrics:  http://localhost:$(PORT)/metrics"
	@echo ""

# Start with Docker Compose watch (development mode with hot-reload)
dev:
	docker compose build --no-cache
	@echo ""
	@echo "🔧 Starting in development mode with hot-reload..."
	@echo ""
	@echo "🚀 API will be running at: http://localhost:$(PORT)"
	@echo ""
	@echo "Endpoints:"
	@echo "  Health:   http://localhost:$(PORT)/health/live"
	@echo "  Ready:    http://localhost:$(PORT)/health/ready"
	@echo "  Webhook:  http://localhost:$(PORT)/webhook"
	@echo "  Messages: http://localhost:$(PORT)/messages"
	@echo "  Stats:    http://localhost:$(PORT)/stats"
	@echo "  Metrics:  http://localhost:$(PORT)/metrics"
	@echo ""
	LOG_LEVEL=DEBUG docker compose up --watch

# Stop and remove containers and volumes
down:
	docker compose down -v
	@echo "✅ Stopped and removed all containers and volumes"

# Follow logs from the api service
logs:
	docker compose logs -f api

# Run tests (locally with pytest)
test:
	@echo "🧪 Running tests..."
	@set -a && . ./.env.test && set +a && PYTHONPATH=$(PWD) pytest tests/ -v --tb=short
	@rm -f test.db
	@echo "✅ Tests completed"

# Run tests inside Docker container
test-docker:
	@echo "🐳 Running tests in Docker..."
	@set -a && . ./.env.test && set +a && docker compose run --rm \
		--no-deps \
		-v "$(PWD)/app:/app/app:ro" \
		-v "$(PWD)/tests:/app/tests:ro" \
		-e PYTHONPATH=/app \
		-e WEBHOOK_SECRET="$$WEBHOOK_SECRET" \
		-e DATABASE_URL="$$DATABASE_URL" \
		-e LOG_LEVEL="$$LOG_LEVEL" \
		api pytest tests/ -v --tb=short
	@echo "✅ Tests completed"

# Clean up Python cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

# Show help
help:
	@echo "Available targets:"
	@echo "  make up          - Start the Docker Compose stack (build and run in detached mode)"
	@echo "  make dev         - Start with Docker Compose watch (development mode with hot-reload)"
	@echo "  make down        - Stop and remove all containers and volumes"
	@echo "  make logs        - Follow logs from the api service"
	@echo "  make test        - Run the test suite locally"
	@echo "  make test-docker - Run the test suite inside Docker"
	@echo "  make clean       - Remove Python cache files"
	@echo "  make help        - Show this help message"
