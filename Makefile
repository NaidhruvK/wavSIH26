.PHONY: all status test eval run help

PYTHON ?= python3

all: status

status:
	@$(PYTHON) -m service.status

test:
	@if command -v pytest >/dev/null 2>&1; then \
		pytest tests/contract/ tests/service/ tests/eval/ tests/e2e/ -v; \
	else \
		$(PYTHON) -m unittest tests/contract/test_stage_contract.py tests/contract/test_registry_contract.py tests/service/test_config.py tests/service/test_db.py tests/service/test_mocks.py tests/service/test_job_runner.py tests/service/test_orchestrator.py tests/service/test_main.py tests/eval/test_metrics.py tests/eval/test_harness.py tests/e2e/test_e2e_pipeline.py; \
	fi

eval:
	@$(PYTHON) -m eval

run:
	@$(PYTHON) -c "from service.mocks import make_mock_report; import json; rep = make_mock_report(); print('=== RAAYA LOCAL RUN (PHASE 2 MOCK REPORT) ==='); print(json.dumps(rep.model_dump(), indent=2))"

help:
	@echo "Raaya (wavSIH26) build targets:"
	@echo "  make status - Display repository and service implementation status"
	@echo "  make test   - Run Contract, Service, and Eval test suites"
	@echo "  make eval   - Execute evaluation harness demonstration"
	@echo "  make run    - Execute local Phase 2 mock report demonstration"
