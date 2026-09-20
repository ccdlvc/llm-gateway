# LLM Gateway Makefile
# =====================
# 
# Quick commands:
#   make start       - Start the proxy server
#   make cli add     - Add an account via CLI
#   make test        - Run tests
#   make demo        - Run the demo
#   make clean       - Remove build artifacts

.PHONY: all start stop cli add remove budget pool status demo test clean help

all: start

start:
	@echo "Starting LLM Gateway proxy server..."
	@python -m llm_gateway proxy --host 0.0.0.0 --port 8080 &
	@echo "  Server running at http://localhost:8080"
	@echo "  Health check: http://localhost:8080/health"

stop:
	@pkill -f "python.*llm_gateway proxy" || true
	@echo "Server stopped."

cli-add:
	@python cli.py add-account --name $(NAME) --api-key $(API_KEY) --balance $(BALANCE)

cli-remove:
	@python cli.py remove-account --id $(ID)

cli-budget:
	@python cli.py set-budget --account-id $(ID) --limit $(LIMIT)

cli-pool:
	@python cli.py pool-status

cli-show:
	@python cli.py show-accounts

demo:
	@cd ../client-side/zed-plugin && python demo.py

test:
	@python -m pytest tests/ -v

clean:
	@rm -f gateway.db gateway.db-journal gateway.db-wal
	@echo "Cleaned up database files."

help:
	@echo "LLM Gateway Makefile"
	@echo ""
	@echo "Commands:"
	@echo "  make start     - Start the proxy server"
	@echo "  make stop      - Stop the proxy server"
	@echo "  make cli-add   - Add an account (NAME, API_KEY, BALANCE)"
	@echo "  make cli-pool  - Show pool status"
	@echo "  make demo      - Run the demo"
	@echo "  make clean     - Remove database files"
	@echo "  make help      - Show this help"
