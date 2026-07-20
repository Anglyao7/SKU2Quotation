PYTHON ?= python3
API_VENV := apps/api/.venv
API_PYTHON := $(API_VENV)/bin/python

.PHONY: setup setup-api setup-web dev-api dev-web test test-api build build-web migrate

setup: setup-api setup-web

setup-api:
	$(PYTHON) -m venv $(API_VENV)
	$(API_PYTHON) -m pip install -r apps/api/requirements.txt

setup-web:
	cd apps/web && npm ci

dev-api:
	cd apps/api && .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web:
	cd apps/web && npm run dev

test: test-api build-web

test-api:
	cd apps/api && .venv/bin/python -m pytest -q

build: build-web

build-web:
	cd apps/web && npm run build

migrate:
	cd apps/api && .venv/bin/alembic upgrade head
