# scango-api

A mini Scan & Go checkout backend built with Django and Django REST Framework.

## Running the tests

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

## Running with Docker

```powershell
docker compose up --build
```

This starts PostgreSQL 16 and the API on http://localhost:8000, running migrations first.
Without Docker the app uses SQLite.

> **Untested:** Docker was not available on the machine these files were written on, so
> `Dockerfile` and `docker-compose.yml` have not been run yet.
