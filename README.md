# liveaux

liveaux heeft twee helften:

- **Out** – alles wat er te doen is in de stad (Berlijn en Hamburg): concerten, clubavonden, tentoonstellingen,
  films, theater, dans, comedy, lezingen en meer. Met een persoonlijk logboek van waar je bent geweest.
- **In** – een persoonlijke bibliotheek van wat je thuis kijkt, leest, speelt en luistert: films, series, anime,
  boeken, comics, manga, games, bordspellen, albums en podcasts. Een eigen versie van
  [Floppy](https://github.com/dannyvfilms/Floppy) (een eigen Trakt, Letterboxd en Goodreads), ingebouwd in liveaux.

De voorpagina (`/`) brengt beide samen: je week in de stad naast je volgende aflevering, wat je bezig bent en
wat er uitkomt.

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

- <http://127.0.0.1:8000/> – de voorpagina (Out en In)
- <http://127.0.0.1:8000/whats-on/> – de hele agenda
- <http://127.0.0.1:8000/week/> – deze week, per stad
- <http://127.0.0.1:8000/library/> – je bibliotheek
- <http://127.0.0.1:8000/admin/> – beheer (backend)

Tests draaien: `uv run python manage.py test`

## Accounts

Iedereen logt in met e-mail en wachtwoord (django-allauth, met e-mailbevestiging).
Lokaal verschijnen de bevestigingsmails in de terminal waar `runserver` draait.

- **Fans:** evenementen opslaan en zalen, artiesten en organisatoren volgen → *My liveaux* (`/me/`)
- **Zalen, organisatoren, artiesten:** een account kan lid zijn van zo'n pagina, als *owner* of *editor*.
  Zalen en organisatoren plaatsen hun eigen evenementen; artiesten beheren hun profiel.
- Artiest- en organisatorpagina's maken gebruikers zelf aan. Toegang tot een **zaal** geef je in de
  admin: open de zaal en voeg iemand toe onder *Venue members*.

## Soorten evenementen

Elk evenement heeft een **categorie** (Music, Club night, Exhibition, Film, Theatre, Dance, Comedy,
Talk & reading, Festival, Kids & family, Other). Categorieën beheer je in de admin (*Categories*):
toevoegen, hernoemen, of de volgorde van de filterknoppen aanpassen met *position*.

Een evenement kan ook een **einddatum** hebben. Dat is voor dingen die meerdere dagen lopen, zoals
een tentoonstelling of een filmreeks. Zolang die loopt staat ze bovenaan onder *On now*, en op de
weekpagina één keer onder *All week* in plaats van elke dag opnieuw. Zo'n evenement kun je
opslaan zolang het loopt, en in je logboek zetten zodra het begonnen is.

Bestaande evenementen krijgen bij de migratie de categorie *Music*.

## Logboek

Op elke evenementpagina van iets dat al begonnen is staat **Ik was erbij** (*I was there*).
Daarna kun je een cijfer (1–10) en een korte notitie toevoegen. Onder *My log* (`/me/log/`) staan
al je bezoeken, met per jaar een jaaroverzicht (`/me/log/2026/`).

Privacy:

- Het logboek is standaard **privé**. In de instellingen kun je het openbaar maken; dan staat het
  op `/people/<id>/` met je naam, nooit je e-mailadres.
- Gebruikers downloaden al hun gegevens (JSON) en verwijderen hun account zelf, onder *Account settings*.
- Privacyverklaring: `/privacy/`. Het contactadres daarin komt uit `LIVEAUX_CONTACT_EMAIL`
  (standaard `privacy@liveaux.eu`; zorg dat dat adres bestaat of stel een ander in).
- Lettertypes worden vanaf liveaux zelf geserveerd, niet via Google Fonts.

## Bibliotheek (In)

Zoeken en toevoegen via `/library/search/`. De gegevens komen van:

| Soort | Bron | Sleutel nodig |
|---|---|---|
| Films, series (met seizoenen en afleveringen) | TMDB | `TMDB_API_KEY` (v3-sleutel of v4-token) |
| Anime, manga | AniList | nee |
| Boeken | Open Library | nee |
| Albums | MusicBrainz | nee |
| Podcasts | Apple Podcasts-directory | nee |
| Games | IGDB | `IGDB_CLIENT_ID` + `IGDB_CLIENT_SECRET` (Twitch-app) |
| Comics, bordspellen | met de hand | – |

Zonder sleutel kun je die soorten nog steeds met de hand toevoegen; later koppel je ze met *Find details*.
Alle verzoeken gaan via de server, en covers worden door liveaux zelf opgeslagen en geserveerd: de browser
van bezoekers praat nooit met die diensten.

Wat er in zit:

- **Status, score, voortgang, data en notities** per titel; per soort telt voortgang anders
  (afleveringen, pagina's, hoofdstukken, sessies).
- **Inchecken** (*Watched it*, *Read a chapter*, *Log a session*…), met datum, minuten en notitie. Per aflevering of
  een heel seizoen tegelijk. Opnieuw kijken telt als herhaling. *Undo* draait een check-in terug.
- **Up next**: van elke serie die je kijkt de volgende aflevering en hoeveel tijd je nog hebt.
- **Diary** (`/me/diary/`): alle check-ins én de evenementen uit je logboek, op volgorde.
- **Kalender** (`/library/calendar/`): nieuwe afleveringen, releases en je opgeslagen evenementen, ook als
  iCal-feed voor je telefoon.
- **Stats** (`/library/stats/`): uren per soort, check-ins per dag en uur, streaks, genres, makers, beste
  titels en jaar-op-jaar. Inclusief je avonden uit.
- **Lijsten** (`/lists/`): privé of openbaar (met RSS), of *smart*: ze vullen zich met regels
  (soort, status, minimale score, genre, jaren).
- **Collectie**: welke exemplaren je hebt (Blu-ray, vinyl, paperback…).
- **Discover**: aanbevelingen op basis van wat je hoog scoorde (TMDB), wat populair is op liveaux, en je planning.
- **Import/export** (`/library/import/`): CSV van Letterboxd, Goodreads, IMDb of liveaux zelf; export als CSV.
  Alles staat ook in de JSON-download onder *Account settings*.
- **Koppelen** (`/library/connect/`): webhooks voor Plex en Jellyfin (bekeken films en afleveringen worden
  automatisch ingecheckt), en een kleine JSON-API onder `/api/v1/` (`entries/`, `plays/`, `calendar/`) met
  `Authorization: Bearer <token>`. Het token is ook het geheim in de kalender- en webhook-adressen; je maakt
  zelf een nieuw aan als het uitlekt.
- **Privacy**: de bibliotheek is standaard privé. Met *Public library* in de instellingen staat hij op
  `/people/<id>/library/`.

Nieuwe afleveringen en releasedata ophalen (dagelijks):

```bash
uv run python manage.py refresh_library
```

Met docker-compose gebeurt dat vanzelf (service `refresh`).

## Recensies, reacties en delen

Op elke evenement- en titelpagina staan onderaan **recensies** en **reacties**.

- **Recensie:** één per persoon per evenement of titel, met tekst en eventueel een spoilervlag (dan is de
  tekst wazig tot je op *Spoilers · show* tikt). Het cijfer wordt niet dubbel opgeslagen: bij een titel is het
  je score in de bibliotheek, bij een evenement je cijfer in het logboek. Wie een recensie schrijft zonder
  dat de titel in de bibliotheek staat, krijgt hem erbij (als *Completed*); bij een evenement komt er een
  logboekregel bij. Evenementen recenseer je pas als ze begonnen zijn, net als bij *Ik was erbij*.
  Het gemiddelde op de pagina telt alleen cijfers uit recensies, want die zijn openbaar.
- **Reacties:** plat, zonder draadjes: op een recensie (`/reviews/<id>/`) of direct op een evenement of titel
  ("gaat er nog iemand?"). Je eigen reacties en recensies verwijder je zelf.
- **Likes** op recensies: één per persoon, nog een keer tikken haalt hem weg. Je eigen recensie kun je niet liken.
- **Namen:** overal staat `public_name`, nooit het e-mailadres. Heb je nog geen naam, dan vraagt het formulier
  er eerst om (*Your name, as others see it*).
- **Openbaar:** recensies en reacties zijn openbaar, ook als logboek en bibliotheek privé zijn. Iemands recensies
  staan op `/people/<id>/reviews/`. Uitzondering: over met de hand toegevoegde titels ziet alleen wie ze
  heeft of maakte iets.
- **Nieuwste recensies** staan onderaan *Live* (evenementen) en de bibliotheek (titels).
- **Delen:** de knop *Share* opent op de telefoon het deelmenu (Web Share API) en kopieert elders de link.
  Pagina's hebben Open Graph- en Twitter-tags (titel, beschrijving, cover), zodat gedeelde links een voorbeeld tonen.

Moderatie:

- Alleen ingelogde gebruikers schrijven, liken en melden. Er is een limiet per gebruiker (standaard 5 reacties
  per minuut, 5 nieuwe recensies per 10 minuten, 10 meldingen per uur), geteld in de database. Aan te passen met
  `SOCIAL_LIMITS` in de settings, bijvoorbeeld `{"comment": (5, 60)}`.
- Een gemelde recensie of reactie staat in de admin onder *Reports*. Kies *Hide* (weg voor iedereen behalve
  staff; alle open meldingen erover worden afgesloten) of *Dismiss*. Staff kan ook direct op de pagina
  op *Hide* drukken, en in de admin onder *Reviews* en *Comments* verbergen of weer tonen.
- Bij het verwijderen van een account gaan recensies, reacties, likes en meldingen mee; ze staan ook in de JSON-export.

## Steden

Steden beheer je in de admin (*Cities*). Elke zaal hoort bij een stad. De weekpagina's staan op
`/week/<stad>/`, bijvoorbeeld `/week/hamburg/`.

## Evenementen indienen door zalen

Zalen, musea, bioscopen en theaters zonder eigen liveaux-pagina dienen evenementen in via `/submit/` (inloggen vereist).
Die komen in de admin onder *Event submissions*. Selecteer ze en kies de actie
*Approve and publish* of *Reject*; de indiener krijgt een e-mail. Een nieuwe zaal uit een
inzending wordt bij goedkeuring automatisch aangemaakt. Wil je bij elke nieuwe inzending
gemaild worden, zet dan `DJANGO_ADMIN_EMAILS`.

> Heb je al een `db.sqlite3` van vóór de accounts? Verwijder die en draai `migrate`,
> `createsuperuser` en `loaddata berlin_events` opnieuw. Het User-model is veranderd.

## Structuur

- `config/` – projectinstellingen (tijdzone `Europe/Berlin`)
- `accounts/` – eigen User-model (inloggen met e-mail), *My liveaux* en instellingen
- `events/` – steden, zalen, organisatoren (in de code: Promoter), artiesten, evenementen, inzendingen, en de beheerpagina's (`views_manage.py`)
- `logbook/` – het logboek (*Ik was erbij*), openbare logboeken en jaaroverzichten
- `social/` – recensies, reacties, likes en meldingen; de blokken voor andere pagina's staan in
  `social/templates/social/_*.html` (één `{% include %}` per pagina)
- `library/` – de bibliotheek: modellen (`Item`, `Episode`, `Entry`, `Play`, `MediaList`, `Copy`), bronnen
  (`providers.py`), inchecken en kalender (`services.py`), stats, import/export, Plex/Jellyfin (`scrobble.py`)
  en de API (`views_api.py`)
- `config/views.py` – de voorpagina
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
| `TMDB_API_KEY` | films en series zoeken (optioneel) |
| `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` | games zoeken (optioneel) |

Een secret key maken:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Lokaal verandert er niets: zonder deze variabelen draait alles met SQLite en `DEBUG` aan.

Op een eigen server naast andere sites: zie [`deploy/README.md`](deploy/README.md).
