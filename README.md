# liveaux

Django-project voor live-evenementen in Berlijn.

## Starten

Vereist [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                      # virtualenv + Django installeren
uv run python manage.py migrate              # tabellen aanmaken
uv run python manage.py createsuperuser      # admin-account
uv run python manage.py loaddata berlin_events   # optioneel: 10 zalen + 20 voorbeeld-evenementen
uv run python manage.py runserver
```

Daarna:

- <http://127.0.0.1:8000/> – de website (frontend)
- <http://127.0.0.1:8000/admin/> – beheer (backend)

Tests draaien: `uv run python manage.py test`

## Structuur

- `config/` – projectinstellingen (tijdzone `Europe/Berlin`)
- `events/` – app met de modellen `Venue` (zaal) en `Event` (evenement)
- `events/fixtures/berlin_events.json` – voorbeelddata: echte Berlijnse zalen, verzonnen programma

## Online zetten (productie)

Het project draait in productie via de `Dockerfile`: Gunicorn als webserver,
WhiteNoise voor CSS/afbeeldingen en PostgreSQL als database. Bij elke start
worden migraties automatisch uitgevoerd.

Stel deze omgevingsvariabelen in bij je hostingplatform (zie `.env.example`):

| Variabele | Voorbeeld |
|---|---|
| `DJANGO_SECRET_KEY` | lange willekeurige string (zie hieronder) |
| `DJANGO_ALLOWED_HOSTS` | `liveaux.eu,www.liveaux.eu` |
| `DATABASE_URL` | wordt meestal door het platform zelf ingevuld |

Een secret key maken:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Lokaal verandert er niets: zonder deze variabelen draait alles met SQLite en `DEBUG` aan.
