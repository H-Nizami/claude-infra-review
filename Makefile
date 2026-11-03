SHELL := /bin/bash
.DEFAULT_GOAL := help

# Pinned binaries from `make tools` (.bin/) first; PATH only as a fallback.
tool = $(shell if [ -x .bin/$(1) ]; then echo .bin/$(1); else command -v $(1) || echo .bin/$(1); fi)
ACTIONLINT := $(call tool,actionlint)
SHELLCHECK := $(call tool,shellcheck)
D2 := $(call tool,d2)
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else command -v python3; fi)
export D2

UP_DOWN_MSG := not applicable (CI-only project)

.PHONY: all help tools lint test diagram up down

all: lint test diagram ## Run lint, test and diagram

help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z]+:.*## / {printf "  %-8s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

tools: ## Install pinned tool binaries into .bin/ (sha256-verified)
	scripts/tools.sh d2 actionlint gitleaks trivy terraform tofu tflint kubeconform

lint: ## actionlint, shellcheck, d2 validate, hygiene checks
	$(ACTIONLINT)
	$(SHELLCHECK) scripts/*.sh
	$(D2) validate docs/architecture.d2
	scripts/check-hygiene.sh

test: ## Unit tests (if any) + hygiene checks
	@if [ -f go.mod ]; then go test ./...; \
	elif [ -d tests ]; then $(PYTHON) -m pytest -q tests; \
	else echo "no tests yet"; fi
	scripts/check-hygiene.sh

diagram: ## Render docs/architecture.d2 to docs/img/architecture.{svg,png}
	scripts/render-diagram.sh

up: ## Bring up the local environment
	@echo "$(UP_DOWN_MSG)"

down: ## Tear down the local environment
	@echo "$(UP_DOWN_MSG)"
