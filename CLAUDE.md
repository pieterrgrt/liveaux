# liveaux

Deployen gaat automatisch: push naar main na groene tests; de server zet het binnen 5 minuten live als CI slaagt en /health werkt. Wijzig docker-compose.yml en Dockerfile alleen als Pieter erom vraagt. Databasemigraties moeten achterwaarts compatibel zijn.

- Tests: `uv run python manage.py test` (draait ook in GitHub Actions, `.github/workflows/test.yml`).
- `/health` wordt beantwoord door `config/health.py` (middleware, vóór HTTPS-redirect en host-check) en controleert de database.
