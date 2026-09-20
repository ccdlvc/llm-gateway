# Makefile for LLM Gateway

.PHONY: help install dev lint test demo server clean

help:
	@echo "LLM Gateway - Available commands:"
	@echo ""
	@echo "  make install       Install dependencies"
	@echo "  make dev           Run in development mode"
	@echo "  make lint          Run linters (black, ruff)"
	@echo "  make test          Run tests"
	@echo "  make demo          Run interactive demo"
	@echo "  make server        Start the proxy server"
	@echo "  make clean         Remove generated files"

install:
	pip install -e ".[dev]"

dev:
	python run.py

lint:
	black .
	ruff check .
	mypy gateway.py cli.py proxy.py

test:
	pytest tests/ -v --cov=gateway --cov-report=term-missing

demo:
	python run_demo.py

server:
	flask --app proxy:app run --host 0.0.0.0 --port $(PORT)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
