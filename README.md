# Business Platform

Minimal technical foundation for a modular B2B SaaS platform. The FastAPI backend and React frontend run directly on the host; Docker Compose runs PostgreSQL only.

## Prerequisites

- Python 3.14
- Node.js 24 and npm 11
- Docker with Docker Compose

This foundation was validated with Python 3.14.7, Node.js 24.19.0, npm 11.17.0, Docker 29.6.2, and Docker Compose 5.3.1.

Copy `.env.example` to `.env` if you want to change the local defaults. The checked-in defaults are intended only for local development.

## Backend setup

From PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Start PostgreSQL from the repository root:

```powershell
docker compose up -d postgres
```

Run migrations and start the API from `backend/`:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

The API is available at `http://localhost:8000`; `GET /health` returns its health status.

Create a migration after changing SQLAlchemy metadata with:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe change"
```

Run backend checks from `backend/`:

```powershell
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ruff.exe check .
```

## Frontend setup

From a second terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

The Vite development server is available at `http://localhost:5173`.

Run frontend checks and a production build from `frontend/`:

```powershell
npm.cmd run lint
npm.cmd run build
```

To stop PostgreSQL, run `docker compose down` from the repository root. The named volume keeps local database data between runs.
