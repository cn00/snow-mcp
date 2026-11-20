SHELL := /usr/bin/env bash

DEV := ./scripts/wsl-dev.sh
SAM_TEMPLATE := template.local.yaml
SAM_HOST := 0.0.0.0
SAM_PORT := 3000

.DEFAULT_GOAL := help

src:
	$(DEV) lambda-src

layer:
	$(DEV) lambda-layer

pkg:
	$(DEV) lambda-package

versions v:
	$(DEV) versions

test: check
	$(DEV) test

sam/validate:
	sam validate --template-file $(SAM_TEMPLATE)

sam/dev: sam/validate
	NO_PROXY=localhost,127.0.0.1,$${NO_PROXY:-} \
	sam local start-api \
		--template-file $(SAM_TEMPLATE) \
		--host $(SAM_HOST) \
		--port $(SAM_PORT)