PY := backend/.venv/bin/python

.PHONY: setup setup-locked dev backend frontend build start test test-backend test-frontend typecheck update-ytdlp clean

setup:            ## Create the Python venv and install all dependencies
	python3 -m venv backend/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements-dev.txt
	cd frontend && npm install

setup-locked:     ## Like setup, but with the exact Python versions MediaLab was tested with
	python3 -m venv backend/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements.lock
	cd frontend && npm ci

dev:              ## Run backend + frontend dev servers
	./scripts/dev.sh

backend:          ## Run only the API (127.0.0.1:8000)
	cd backend && .venv/bin/python -m app --reload

frontend:         ## Run only the Vite dev server (127.0.0.1:5173)
	cd frontend && npm run dev

build:            ## Build the frontend into frontend/dist
	cd frontend && npm run build

start: build      ## Single-process mode: API serves the built UI at http://127.0.0.1:8000
	cd backend && .venv/bin/python -m app

test: test-backend test-frontend   ## All automated tests (no network, no TikTok account needed)

test-backend:     ## Backend tests (FFmpeg integration tests run when ffmpeg is installed)
	cd backend && .venv/bin/python -m pytest

test-frontend:    ## Frontend type-check + unit tests
	cd frontend && npm run typecheck && npm test

typecheck:
	cd frontend && npm run typecheck

update-ytdlp:     ## X and TikTok change often; keep yt-dlp (+ impersonation extra) current
	$(PY) -m pip install -U "yt-dlp[curl-cffi]"

clean:            ## Remove build output and caches (not downloads)
	rm -rf frontend/dist backend/.pytest_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
