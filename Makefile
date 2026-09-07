.PHONY: all status test eval run serve build-ui docker-build docker-run help

DOCKER ?= $(HOME)/.docker/bin/docker
PYTHON ?= python3

all: status

status:
	@$(PYTHON) -m service.status

test:
	@if command -v pytest >/dev/null 2>&1; then \
		pytest tests/contract/ tests/service/ tests/eval/ tests/e2e/ -v; \
	else \
		$(PYTHON) -m unittest tests/contract/test_stage_contract.py tests/contract/test_registry_contract.py tests/service/test_config.py tests/service/test_db.py tests/service/test_mocks.py tests/service/test_job_runner.py tests/service/test_orchestrator.py tests/service/test_main.py tests/service/test_cli.py tests/eval/test_metrics.py tests/eval/test_harness.py tests/e2e/test_e2e_pipeline.py; \
	fi

eval:
	@$(PYTHON) -m eval

run:
	@$(PYTHON) -m service.cli run

serve:
	@$(PYTHON) -m service.cli run

build-ui:
	@cd web && npm run build

docker-build:
	@PATH="$(HOME)/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$$PATH" $(DOCKER) build -t wavsih26:phase8 .

docker-run:
	@PATH="$(HOME)/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:$$PATH" $(DOCKER) run -p 8000:8000 --rm wavsih26:phase8

help:
	@echo "Raaya (wavSIH26) build targets:"
	@echo "  make status       - Display repository and service implementation status"
	@echo "  make test         - Run Contract, Service, Eval, and E2E test suites"
	@echo "  make eval         - Execute evaluation harness demonstration"
	@echo "  make run / serve  - Launch production REST API and Command Center UI"
	@echo "  make build-ui     - Compile Vite React production bundle into web/dist"
	@echo "  make docker-build - Build multi-stage Docker image (wavsih26:phase8)"
	@echo "  make docker-run   - Run containerized Raaya service on port 8000"
