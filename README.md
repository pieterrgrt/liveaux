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

Daarna: <http://127.0.0.1:8000/admin/>

## Structuur

- `config/` – projectinstellingen (tijdzone `Europe/Berlin`)
- `events/` – app met de modellen `Venue` (zaal) en `Event` (evenement)
- `events/fixtures/berlin_events.json` – voorbeelddata: echte Berlijnse zalen, verzonnen programma
