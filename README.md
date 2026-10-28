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

Iedereen logt in met e-mail en wachtwoord (django-allauth). Je blijft een jaar ingelogd (handig op de
iPhone), tot je zelf uitlogt; `SESSION_COOKIE_AGE` (seconden) verandert dat.

E-mail en bevestiging:

- **Zonder mailserver** (`EMAIL_HOST` leeg, of een voorbeeldadres als `smtp.example.com`) gaan mails
  alleen naar de terminal of de logs. Bevestigen is dan *optional*: nieuwe mensen zijn na het
  aanmelden meteen binnen. *Wachtwoord vergeten* zegt dan eerlijk dat er geen mail kan komen en
  noemt `LIVEAUX_CONTACT_EMAIL`. Lokaal (`DEBUG` aan) werkt het wel: de link staat in de terminal.
- **Met een echte SMTP-server** (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`) moeten nieuwe
  mensen eerst hun adres bevestigen (*mandatory*).
- `ACCOUNT_EMAIL_VERIFICATION` (`mandatory`, `optional` of `none`) zet dat zelf vast.

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

| Soort | Zonder sleutel | Met sleutel |
|---|---|---|
| Films | Wikidata + Wikipedia (titel, jaar, regisseur, genres, duur, samenvatting, poster) | TMDB (`TMDB_API_KEY`, v3-sleutel of v4-token) |
| Series (met seizoenen en afleveringen) | TVmaze (afleveringen met datum en duur, status, volgende aflevering) | TMDB |
| Anime, manga | AniList | – |
| Boeken | Open Library (Engelse titel en cover als die er is) | – |
| Albums | MusicBrainz | – |
| Podcasts | Apple Podcasts-directory | – |
| Games | Wikidata + Wikipedia (jaar, ontwikkelaar, genres, cover) | IGDB (`IGDB_CLIENT_ID` + `IGDB_CLIENT_SECRET`, Twitch-app) |
| Comics, bordspellen | met de hand | – |

Alles werkt dus zonder sleutels. Met een sleutel neemt TMDB of IGDB het over voor nieuwe zoekopdrachten;
wat al in je bibliotheek staat blijft bij zijn bron. Zoekresultaten zeggen waar ze vandaan komen.
Met de hand toegevoegde titels koppel je later met *Find details*.
Samenvattingen uit Wikipedia staan er met bronvermelding (CC BY-SA). De zoekfunctie van Apple (iTunes)
geeft geen films meer terug, daarom komen films zonder sleutel van Wikidata.

Alle verzoeken gaan via de server (met een User-Agent met contactadres, korte time-outs en een cache van een
uur voor zoekopdrachten), en covers worden door liveaux zelf opgeslagen en geserveerd: de browser
van bezoekers praat nooit met die diensten.

### Elsewhere: scores van andere sites

Op elke titelpagina staat onder de gegevens het blok **Elsewhere**: wat andere sites ervan vinden, met
score, aantal beoordelingen, een link naar de bron en wanneer liveaux het ophaalde. Daarboven het
gemiddelde cijfer van mensen op liveaux zelf.

- **Wikidata** (CC0): de review-scores die daar staan (Rotten Tomatoes, Metacritic, IMDb, OpenCritic…),
  met aantal reviews en de datum van de meting. liveaux vindt de titel op Wikidata via de id bij de bron
  (TMDB, TVmaze, AniList, Open Library, MusicBrainz, IGDB, Apple Podcasts).
- **TVmaze**, **AniList** (score en op hoeveel lijsten), **Open Library** (cijfer en *want to read / reading /
  read*), **MusicBrainz**, en met sleutel **TMDB** en **IGDB**.
- Alleen officiële API's en open data. IMDb, Letterboxd, Rotten Tomatoes en Metacritic zelf worden nooit
  bezocht of gescrapet; er wordt alleen naar ze gelinkt.

De pagina laadt meteen met wat er is opgeslagen (model `ExternalRating`). Is dat ouder dan zes uur, dan haalt
een klein script (`liveaux.js`) `/library/items/<id>/elsewhere/` op; de server vraagt de bronnen opnieuw
(korte time-outs, een bron die faalt valt stil weg) en het blok wordt vervangen. Zonder JavaScript zie je de
opgeslagen scores. *Refresh details* en `refresh_library` halen ze ook op.

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
- **Discover**: aanbevelingen op basis van wat je hoog scoorde (alleen met TMDB-sleutel), wat populair is op liveaux, en je planning.
- **Import/export** (`/library/import/`): CSV van Letterboxd, Goodreads, IMDb of liveaux zelf; export als CSV.
  Alles staat ook in de JSON-download onder *Account settings*.
- **Koppelen** (`/library/connect/`): webhooks voor Plex en Jellyfin (bekeken films en afleveringen worden
  automatisch ingecheckt), en een kleine JSON-API onder `/api/v1/` (`entries/`, `plays/`, `calendar/`) met
  `Authorization: Bearer <token>`. Het token is ook het geheim in de kalender- en webhook-adressen; je maakt
  zelf een nieuw aan als het uitlekt.
- **Privacy**: de bibliotheek is standaard privé. Met *Public library* in de instellingen staat hij op
  `/people/<id>/library/`.

Nieuwe afleveringen, releasedata en scores van elders ophalen (dagelijks):

```bash
uv run python manage.py refresh_library            # --no-ratings: zonder scores; --ratings-limit 300
```

Met docker-compose gebeurt dat vanzelf (service `refresh`).

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
- `library/` – de bibliotheek: modellen (`Item`, `Episode`, `Entry`, `Play`, `MediaList`, `Copy`, `ExternalRating`),
  bronnen (`providers.py`), scores van elders (`ratings.py`), inchecken en kalender (`services.py`), stats, import/export, Plex/Jellyfin (`scrobble.py`)
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
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | echte SMTP-server voor bevestigings- en resetmails (optioneel) |
| `ACCOUNT_EMAIL_VERIFICATION` | `mandatory`, `optional` of `none` (optioneel, zie *Accounts*) |
| `TMDB_API_KEY` | films en series via TMDB in plaats van Wikidata/TVmaze (optioneel) |
| `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` | games via IGDB in plaats van Wikidata (optioneel) |

Een secret key maken:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Lokaal verandert er niets: zonder deze variabelen draait alles met SQLite en `DEBUG` aan.

Op een eigen server naast andere sites: zie [`deploy/README.md`](deploy/README.md).

## Wat Pieter nog moet doen

Dingen die alleen jij kunt regelen (alles werkt ook zonder):

1. **SMTP instellen** in `.env` op de server: `EMAIL_HOST` (nu `smtp.example.com`, dat telt als geen
   server), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, eventueel `EMAIL_PORT`/`EMAIL_USE_TLS`. Bijvoorbeeld de
   SMTP van je mailprovider of een dienst als Postmark/Brevo, met `noreply@liveaux.eu` als afzender
   (SPF/DKIM voor liveaux.eu). Daarna is bevestigen weer *mandatory* en werkt *Wachtwoord vergeten*.
2. **Gratis TMDB-sleutel** (optioneel): account op themoviedb.org → Settings → API → *Request an API key*
   (persoonlijk gebruik), en `TMDB_API_KEY` in `.env`. Dan: TMDB voor films en series, TMDB-scores en Discover.
3. **IGDB** (optioneel): een Twitch-developer-app op dev.twitch.tv → `IGDB_CLIENT_ID` en `IGDB_CLIENT_SECRET`.
4. Controleer dat `LIVEAUX_CONTACT_EMAIL` bestaat: de resetpagina verwijst ernaar zolang er geen SMTP is.
