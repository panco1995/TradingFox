.DEFAULT_GOAL := help
PYTHON ?= python3.13
PY := quant/.venv/bin/python
PIP := quant/.venv/bin/pip

.PHONY: help up down logs ps venv install test lint fmt fetch inspect quality api build-api

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:  ## start mysql + redis
	docker compose up -d
	docker compose ps

down:  ## stop containers (keeps volumes)
	docker compose down

logs:  ## tail container logs
	docker compose logs -f --tail=100

venv:  ## create python venv
	$(PYTHON) -m venv quant/.venv

install: venv  ## install python deps (editable)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "quant[dev]"

test:  ## run python tests
	cd quant && .venv/bin/python -m pytest -q

lint:  ## lint python code
	cd quant && .venv/bin/ruff check .

fmt:  ## auto-format python code
	cd quant && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

fetch:  ## fetch last 2 days of BTCUSDT 1m bars
	cd quant && .venv/bin/python -m quant.cli fetch --symbol BTCUSDT --days 2

watch:  ## stream live bars (ctrl-c to stop)
	cd quant && .venv/bin/python -m quant.cli watch --symbol BTCUSDT --symbol ETHUSDT

inspect:  ## summarise stored BTCUSDT bars
	cd quant && .venv/bin/python -m quant.cli inspect --symbol BTCUSDT --days 2 --svg ../data/chart.svg

quality:  ## check data quality for the last 30 days
	cd quant && .venv/bin/python -m quant.cli quality --symbol BTCUSDT --days 30

build-api:  ## build the go api
	cd backend && go build -o bin/api ./cmd/api

api:  ## run the go api on :8080
	cd backend && go run ./cmd/api
