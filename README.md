# Booking System for Small Businesses

![CI](https://github.com/RosPyt/booking-system/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A web app for barbershops, salons, gyms, clinics and similar businesses: customers book appointments online and
the owner manages them from a secured admin panel. The customer-facing UI is in Greek.

<!-- Add a screenshot here: ![Screenshot](docs/screenshot.png) -->

## Features
- **3-step booking:** category (Men / Women) → service → date and time, with a live summary and total price.
- **Smart form:** the customer types something like "haircut and beard Thursday afternoon" and the form fills itself
  in (Claude AI, or simple rule-based parsing when no API key is set).
- **Admin panel:** upcoming bookings, cancellations, and service management (name, duration, price, category).
- **Configurable:** opening hours, days off, time zone, booking window (2 weeks by default) and business name, all via environment variables.

## Tech stack
Python · Flask · SQLite (WAL) · Vanilla JS/CSS · Anthropic API (optional) · Gunicorn · pytest · GitHub Actions · Docker

## Design decisions
- **No double bookings.** The availability check and the insert run inside a single `BEGIN IMMEDIATE` transaction,
  and overlaps are computed from each service's *duration*, not just its start time. A test fires 10 concurrent
  bookings for the same slot and exactly one succeeds.
- **AI with a fallback.** If the API key is missing or the call fails, the app keeps working with rules. The model's
  output is treated as untrusted input: every field (service id, date, category) is validated before it reaches the client.
- **Security.**
  - Refuses to start in production without a strong `SECRET_KEY` and an admin password.
  - CSRF tokens on all admin actions, rate limiting on login (5 failures / 5 min) and on the AI endpoint, fresh session after login.
  - Constant-time password comparison, optionally against a hash (`ADMIN_PASSWORD_HASH`).
  - Strict Content-Security-Policy (no inline scripts), `HttpOnly`/`SameSite`/`Secure` cookies, parameterized SQL, Jinja auto-escaping.
- **Correct time handling.** All "in the past" checks use the business time zone (`TIMEZONE`), not the server's.
- **Bounded booking window.** Dates in the past or beyond `MAX_DAYS_AHEAD` are rejected by the server, not just the date picker.

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # Windows: copy .env.example .env
python app.py
```
Customers: http://127.0.0.1:5000 · Admin: http://127.0.0.1:5000/admin (password: the `ADMIN_PASSWORD` value in your `.env`).

`.env` holds your real secrets and is git-ignored. `.env.example` is the committed template.

## Tests
```bash
pytest
```
Covers availability and overlaps, concurrent bookings, input validation, the booking window, admin access control /
CSRF / rate limiting, and the smart form (including the AI fallback).

## Configuration
See [`.env.example`](.env.example) for every variable. The main ones:

| Variable | Description |
|---|---|
| `SECRET_KEY`, `ADMIN_PASSWORD` / `ADMIN_PASSWORD_HASH` | Required in production |
| `OPEN_HOUR`, `CLOSE_HOUR`, `CLOSED_DAYS`, `STEP_MINUTES` | Opening hours and days off (`0`=Monday … `6`=Sunday) |
| `TIMEZONE`, `MAX_DAYS_AHEAD` | Business time zone and how many days ahead bookings are accepted (default 14) |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Optional, enables the AI-powered smart form |
| `DB_PATH` | Location of the SQLite file |
| `TRUST_PROXY=1` | Set when running behind a reverse proxy (correct client IP for rate limits) |

## Deployment
**Render / Heroku-style:** start command `gunicorn 'app:create_app()'` (a `Procfile` is included). Add the environment
variables (without `FLASK_DEBUG`, and with `TRUST_PROXY=1`).

**Docker:**
```bash
docker build -t booking .
docker run -p 8000:8000 -v booking-data:/data -e SECRET_KEY=... -e ADMIN_PASSWORD=... booking
```

> **Note:** on free hosting tiers the disk is wiped on every restart, which deletes the SQLite database. For real use,
> add a persistent disk/volume (and set `DB_PATH`) or move to PostgreSQL.

## Project layout
```
app.py          Flask app factory, routes, database
smartform.py    Smart form (rules + Claude + output validation)
security.py     CSRF, password check, rate limiter
templates/      Jinja templates · static/  CSS and JS
tests/          pytest suite
```

## Ideas for extension
Confirmation emails · SMS reminders · multiple staff/resources · per-day opening hours · PostgreSQL · pagination and search in the admin

## License
MIT, see [LICENSE](LICENSE).
