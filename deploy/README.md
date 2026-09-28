# liveaux op een eigen server (naast andere sites)

liveaux draait in Docker (Django + PostgreSQL) en luistert alleen op
`127.0.0.1:8001`. De webserver die al op de server draait (Caddy of nginx)
stuurt `liveaux.eu` door naar die poort en regelt HTTPS.

## Eenmalig

1. **DNS bij Mijndomein:** A-record `@` → IP van de server, en A-record `www` → hetzelfde IP
   (heeft de server IPv6: ook AAAA-records).
2. **Op de server:**
   ```bash
   git clone https://github.com/pieterrgrt/liveaux.git ~/liveaux
   cd ~/liveaux
   cp .env.example .env
   nano .env            # secret key, wachtwoord, poort invullen
   docker compose up -d --build
   curl -I http://127.0.0.1:8001   # moet antwoorden (301 naar https is goed)
   ```
   Secret key maken: `openssl rand -base64 48`
3. **Webserver:** voeg `deploy/Caddyfile.example` of `deploy/nginx.conf.example` toe
   aan de bestaande config en herlaad.
4. **Admin-account en voorbeelddata:**
   ```bash
   docker compose exec web python manage.py createsuperuser
   docker compose exec web python manage.py loaddata berlin_events
   ```

## Nieuwe versie live zetten

```bash
cd ~/liveaux && ./deploy/update.sh
```

## Handig

- Logs: `docker compose logs -f web`
- Back-up database: `docker compose exec db pg_dump -U liveaux liveaux > backup.sql`
