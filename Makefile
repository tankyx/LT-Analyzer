# LT-Analyzer Makefile
# Convenient commands for development and testing

.PHONY: help test test-frontend test-backend test-coverage test-watch install dev clean

# Default target
help:
	@echo "LT-Analyzer Development Commands"
	@echo "================================"
	@echo ""
	@echo "Testing:"
	@echo "  make test              Run all tests"
	@echo "  make test-frontend     Run frontend tests only"
	@echo "  make test-backend      Run backend tests only"
	@echo "  make test-coverage     Run all tests with coverage"
	@echo "  make test-watch        Run frontend tests in watch mode"
	@echo ""
	@echo "Development:"
	@echo "  make install           Install all dependencies"
	@echo "  make dev               Start development servers"
	@echo "  make clean             Clean build artifacts and caches"
	@echo ""
	@echo "Production:"
	@echo "  make build             Build for production"
	@echo "  make start             Start production servers"

# Testing targets
test:
	@./test.sh

test-frontend:
	@./scripts/test-frontend.sh

test-backend:
	@./scripts/test-backend.sh

test-coverage:
	@./test.sh --coverage

test-watch:
	@./scripts/test-frontend.sh watch

# Development targets
install:
	@echo "📦 Installing dependencies..."
	@cd racing-analyzer && npm install
	@python3 -m venv racing-venv || true
	@. racing-venv/bin/activate && pip install -r requirements.txt
	@echo "✅ Dependencies installed!"

dev:
	@echo "🚀 Starting development servers..."
	@echo "Starting backend on port 5000..."
	@. racing-venv/bin/activate && python race_ui.py &
	@echo "Starting frontend on port 3000..."
	@cd racing-analyzer && npm run dev

# Build targets
build:
	@echo "🔨 Building for production..."
	@cd racing-analyzer && npm run build
	@echo "✅ Build complete!"

# Clean targets
clean:
	@echo "🧹 Cleaning build artifacts..."
	@rm -rf racing-analyzer/.next
	@rm -rf racing-analyzer/node_modules
	@rm -rf racing-analyzer/coverage
	@rm -rf htmlcov
	@rm -rf .pytest_cache
	@rm -rf __pycache__
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "✅ Clean complete!"

# Production targets
start:
	@echo "🚀 Starting production servers..."
	@pm2 start start-selenium.sh --name "lt-analyzer-backend"
	@pm2 start start-frontend.sh --name "lt-analyzer-frontend"
	@pm2 status