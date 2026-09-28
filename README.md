# liveaux

Django-project voor live-evenementen (Berlijn en Hamburg), met een persoonlijk logboek van de concerten waar je bent geweest.

## Starten

Vereist [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                      # virtualenv + Django installeren
uv run python manage.py migrate              # tabellen aanmaken
uv run python manage.py createsuperuser      # admin-account
uv run python manage.py loaddata berlin_events hamburg_events   # optioneel: voorbeeldzalen en -evenementen
uv run python manage.py runserver
```

Daarna:

- <http://127.0.0.1:8000/> – de website (frontend)
- <http://127.0.0.1:8000/week/> – deze week, per stad
- <http://127.0.0.1:8000/admin/> – beheer (backend)

Tests draaien: `uv run python manage.py test`

## Accounts

Iedereen logt in met e-mail en wachtwoord (django-allauth, met e-mailbevestiging).
Lokaal verschijnen de bevestigingsmails in de terminal waar `runserver` draait.

- **Fans:** evenementen opslaan en zalen, artiesten en promoters volgen → *My liveaux* (`/me/`)
- **Zalen, promoters, artiesten:** een account kan lid zijn van zo'n pagina, als *owner* of *editor*.
  Zalen en promoters plaatsen hun eigen evenementen; artiesten beheren hun profiel.
- Artiest- en promoterpagina's maken gebruikers zelf aan. Toegang tot een **zaal** geef je in de
  admin: open de zaal en voeg iemand toe onder *Venue members*.

## Logboek

Op elke evenementpagina van een show die al begonnen is staat **Ik was erbij** (*I was there*).
Daarna kun je een cijfer (1–10) en een korte notitie toevoegen. Onder *My log* (`/me/log/`) staan
al je bezoeken, met per jaar een jaaroverzicht (`/me/log/2026/`).

Privacy:

- Het logboek is standaard **privé**. In de instellingen kun je het openbaar maken; dan staat het
  op `/people/<id>/` met je naam, nooit je e-mailadres.
- Gebruikers downloaden al hun gegevens (JSON) en verwijderen hun account zelf, onder *Account settings*.
- Privacyverklaring: `/privacy/`. Het contactadres daarin komt uit `LIVEAUX_CONTACT_EMAIL`
  (standaard `privacy@liveaux.eu`; zorg dat dat adres bestaat of stel een ander in).
- Lettertypes worden vanaf liveaux zelf geserveerd, niet via Google Fonts.

## Steden

Steden beheer je in de admin (*Cities*). Elke zaal hoort bij een stad. De weekpagina's staan op
`/week/<stad>/`, bijvoorbeeld `/week/hamburg/`.

## Evenementen indienen door zalen

Zalen zonder eigen liveaux-pagina dienen evenementen in via `/submit/` (inloggen vereist).
Die komen in de admin onder *Event submissions*. Selecteer ze en kies de actie
*Approve and publish* of *Reject*; de indiener krijgt een e-mail. Een nieuwe zaal uit een
inzending wordt bij goedkeuring automatisch aangemaakt. Wil je bij elke nieuwe inzending
gemaild worden, zet dan `DJANGO_ADMIN_EMAILS`.

> Heb je al een `db.sqlite3` van vóór de accounts? Verwijder die en draai `migrate`,
> `createsuperuser` en `loaddata berlin_events` opnieuw. Het User-model is veranderd.

## Structuur

- `config/` – projectinstellingen (tijdzone `Europe/Berlin`)
- `accounts/` – eigen User-model (inloggen met e-mail), *My liveaux* en instellingen
- `events/` – steden, zalen, promoters, artiesten, evenementen, inzendingen, en de beheerpagina's (`views_manage.py`)
- `logbook/` – het logboek (*Ik was erbij*), openbare logboeken en jaaroverzichten
- `templates/` – gedeelde layout en de opgemaakte inlogpagina's van allauth
- `events/fixtures/` – voorbeelddata: echte zalen in Berlijn en Hamburg, verzonnen programma

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
| `LIVEAUX_CONTACT_EMAIL` | adres voor privacyvragen, staat in de privacyverklaring |
| `DJANGO_ADMIN_EMAILS` | wie een mail krijgt bij een nieuwe inzending (optioneel) |

Een secret key maken:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Lokaal verandert er niets: zonder deze variabelen draait alles met SQLite en `DEBUG` aan.

Op een eigen server naast andere sites: zie [`deploy/README.md`](deploy/README.md).
