"""Σύστημα κρατήσεων για μικρές επιχειρήσεις (Flask + SQLite)."""
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from flask import Flask, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import smartform
from security import RateLimiter, check_password, csrf_token, verify_csrf

WEAK = {"", "change-me", "admin123", "dev-only-secret"}
PHONE_RE = re.compile(r"[+\d ]{8,15}")

SCHEMA = """
create table if not exists services(
  id integer primary key, name text not null, minutes integer not null,
  price real not null, category text not null default 'men');
create table if not exists bookings(
  id integer primary key, service_id integer not null references services(id),
  date text not null, start integer not null, name text not null, phone text not null,
  created text default current_timestamp);
create index if not exists idx_b_date on bookings(date);
"""
MEN = [("Κούρεμα", 30, 12, "men"), ("Γένια", 30, 8, "men"), ("Κούρεμα + γένια", 60, 18, "men")]
WOMEN = [("Κούρεμα", 45, 25, "women"), ("Χτένισμα", 30, 15, "women"),
         ("Βαφή μαλλιών", 90, 45, "women"), ("Μανικιούρ", 45, 18, "women")]
ADD_SERVICE = "insert into services(name,minutes,price,category) values(?,?,?,?)"


# ---------- Ρυθμίσεις ----------
def env_config():
    env = os.getenv
    return {
        "DEBUG": env("FLASK_DEBUG") == "1",
        "SECRET_KEY": env("SECRET_KEY", ""),
        "ADMIN_PASSWORD": env("ADMIN_PASSWORD", ""),
        "ADMIN_PASSWORD_HASH": env("ADMIN_PASSWORD_HASH", ""),
        "DB_PATH": env("DB_PATH", "booking.db"),
        "BUSINESS_NAME": env("BUSINESS_NAME", "Barber Studio"),
        "OPEN_HOUR": int(env("OPEN_HOUR", 9)),
        "CLOSE_HOUR": int(env("CLOSE_HOUR", 18)),
        "CLOSED_DAYS": {int(d) for d in env("CLOSED_DAYS", "6").split(",") if d.strip()},  # 0=Δευτέρα … 6=Κυριακή
        "STEP_MINUTES": int(env("STEP_MINUTES", 30)),
        "MAX_DAYS_AHEAD": int(env("MAX_DAYS_AHEAD", 14)),
        "TIMEZONE": env("TIMEZONE", "Europe/Athens"),
        "TRUST_PROXY": env("TRUST_PROXY") == "1",
        "ANTHROPIC_API_KEY": env("ANTHROPIC_API_KEY", ""),
        "CLAUDE_MODEL": env("CLAUDE_MODEL", "claude-sonnet-4-6"),
    }


def validate_config(cfg):
    if cfg["DEBUG"] or cfg.get("TESTING"):
        cfg["SECRET_KEY"] = cfg["SECRET_KEY"] or "dev-only-secret"
        cfg["ADMIN_PASSWORD"] = cfg["ADMIN_PASSWORD"] or "admin123"
    else:
        if cfg["SECRET_KEY"] in WEAK:
            raise RuntimeError("Ορίστε ένα ισχυρό SECRET_KEY (π.χ. python -c \"import secrets; print(secrets.token_hex(32))\").")
        if not cfg["ADMIN_PASSWORD_HASH"] and cfg["ADMIN_PASSWORD"] in WEAK:
            raise RuntimeError("Ορίστε ADMIN_PASSWORD ή ADMIN_PASSWORD_HASH.")
    if not 0 <= cfg["OPEN_HOUR"] < cfg["CLOSE_HOUR"] <= 24:
        raise RuntimeError("Μη έγκυρο ωράριο: πρέπει OPEN_HOUR < CLOSE_HOUR.")
    return cfg


def create_app(overrides=None):
    if overrides is None:
        load_dotenv()
    cfg = env_config()
    cfg.update(overrides or {})
    app = Flask(__name__)
    app.config.update(validate_config(cfg))
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not (cfg["DEBUG"] or cfg.get("TESTING")),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if cfg["TRUST_PROXY"]:  # πίσω από Render/Heroku/nginx: σωστό IP και https
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    try:
        app.config["TZ"] = ZoneInfo(cfg["TIMEZONE"])
    except ZoneInfoNotFoundError:  # π.χ. Windows χωρίς tzdata: δουλεύουμε με την ώρα του υπολογιστή
        app.logger.warning("Άγνωστη ζώνη ώρας %r (δοκιμάστε: pip install tzdata). Χρήση ώρας συστήματος.", cfg["TIMEZONE"])
        app.config["TZ"] = None
    app.limiter = RateLimiter()
    init_db(app.config["DB_PATH"])
    register_hooks(app)
    register_public(app)
    register_admin(app)
    return app


# ---------- Βάση δεδομένων ----------
def init_db(path):
    c = sqlite3.connect(path)
    c.execute("pragma journal_mode=wal")
    c.executescript(SCHEMA)
    migrated = "category" not in [r[1] for r in c.execute("pragma table_info(services)")]
    if migrated:  # παλιά βάση χωρίς κατηγορίες: οι υπάρχουσες γίνονται «Ανδρικό»
        c.execute("alter table services add column category text not null default 'men'")
    if not c.execute("select 1 from services").fetchone():
        c.executemany(ADD_SERVICE, MEN + WOMEN)
    elif migrated:
        c.executemany(ADD_SERVICE, WOMEN)
    c.commit()
    c.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"], isolation_level=None, timeout=10)  # autocommit
        g.db.row_factory = sqlite3.Row
        g.db.execute("pragma foreign_keys=on")
    return g.db


def get_service(sid):
    if not isinstance(sid, int) or isinstance(sid, bool):
        return None
    return db().execute("select * from services where id=?", (sid,)).fetchone()


def now_local():
    return datetime.now(current_app.config["TZ"])


def free_slots(day, minutes):
    """Ελεύθερες ώρες έναρξης (σε λεπτά από τα μεσάνυχτα), χωρίς επικάλυψη με άλλα ραντεβού."""
    cfg = current_app.config
    try:
        d = date.fromisoformat(day)
    except (TypeError, ValueError):
        return []
    now = now_local()
    today = now.date()
    if d < today or d > today + timedelta(days=cfg["MAX_DAYS_AHEAD"]) or d.weekday() in cfg["CLOSED_DAYS"]:
        return []
    busy = [(r["start"], r["start"] + r["minutes"]) for r in db().execute(
        "select b.start, s.minutes from bookings b join services s on s.id=b.service_id where b.date=?", (day,))]
    floor = now.hour * 60 + now.minute if d == today else -1
    open_, close = cfg["OPEN_HOUR"] * 60, cfg["CLOSE_HOUR"] * 60
    return [t for t in range(open_, close - minutes + 1, cfg["STEP_MINUTES"])
            if t > floor and all(t + minutes <= a or t >= b for a, b in busy)]


def hm(t):
    return f"{t // 60:02d}:{t % 60:02d}"


# ---------- Κοινά hooks ----------
def register_hooks(app):
    app.teardown_appcontext(lambda _: (d := g.pop("db", None)) and d.close())
    app.add_template_filter(hm, "hm")
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.after_request
    def security_headers(resp):
        resp.headers.update({
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                                       "base-uri 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
        })
        if request.path.startswith(("/admin", "/api")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(404)
    @app.errorhandler(405)
    def api_errors(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Μη έγκυρο αίτημα."), e.code
        return e


# ---------- Πελάτες ----------
def register_public(app):
    @app.route("/")
    def index():
        services = [dict(s) for s in db().execute("select * from services order by category, minutes, name")]
        cats = [{"key": k, "label": label} for k, label in (("men", "Ανδρικό"), ("women", "Γυναικείο"))
                if any(s["category"] == k for s in services)]
        cfg, today = app.config, now_local().date()
        return render_template(
            "index.html", business=cfg["BUSINESS_NAME"], services=services, cats=cats,
            open_h=f"{cfg['OPEN_HOUR']:02d}", close_h=f"{cfg['CLOSE_HOUR']:02d}",
            today=today.isoformat(), max_date=(today + timedelta(days=cfg["MAX_DAYS_AHEAD"])).isoformat())

    @app.get("/api/slots")
    def api_slots():
        s = get_service(request.args.get("service", type=int))
        if not s:
            abort(404)
        return jsonify(slots=free_slots(request.args.get("date", ""), s["minutes"]))

    @app.post("/api/book")
    def api_book():
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            return jsonify(error="Μη έγκυρο αίτημα."), 400
        name, phone = str(d.get("name") or "").strip(), str(d.get("phone") or "").strip()
        s, day, start = get_service(d.get("service_id")), d.get("date"), d.get("start")
        if (not s or not isinstance(day, str) or not isinstance(start, int) or isinstance(start, bool)
                or not 2 <= len(name) <= 60 or not PHONE_RE.fullmatch(phone)):
            return jsonify(error="Παρακαλούμε ελέγξτε το ονοματεπώνυμο και το τηλέφωνο."), 400
        con = db()
        con.execute("BEGIN IMMEDIATE")  # κλειδώνει τη βάση ώστε να μην γίνουν δύο κρατήσεις ταυτόχρονα
        try:
            if start not in free_slots(day, s["minutes"]):
                con.execute("ROLLBACK")
                return jsonify(error="Η επιλεγμένη ώρα δεν είναι πλέον διαθέσιμη. Παρακαλούμε επιλέξτε άλλη."), 409
            con.execute("insert into bookings(service_id,date,start,name,phone) values(?,?,?,?,?)",
                        (s["id"], day, start, name, phone))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return jsonify(ok=True, text=f"Η κράτησή σας επιβεβαιώθηκε: {s['name']}, {day}, ώρα {hm(start)}."), 201

    @app.post("/api/parse")
    def api_parse():
        if not app.limiter.allow(f"parse:{request.remote_addr}", limit=20, window=60):
            return jsonify(error="Πάρα πολλά αιτήματα. Δοκιμάστε ξανά σε λίγο."), 429
        body = request.get_json(silent=True)
        text = str(body.get("text") or "")[:300] if isinstance(body, dict) else ""
        services = [dict(s) for s in db().execute("select id,name,minutes,category from services")]
        cfg = app.config
        return jsonify(smartform.parse_request(
            text, services, now_local().date(), cfg["ANTHROPIC_API_KEY"], cfg["CLAUDE_MODEL"], app.logger, cfg["MAX_DAYS_AHEAD"]))


# ---------- Admin ----------
def register_admin(app):
    def admin_only(f):
        @wraps(f)
        def wrapper(*a, **k):
            return f(*a, **k) if session.get("admin") else redirect(url_for("admin"))
        return wrapper

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and request.path.startswith("/admin"):
            verify_csrf()

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        cfg, error, status, ip = app.config, None, 200, f"login:{request.remote_addr}"
        if request.method == "POST":
            if app.limiter.recent(ip, 300) >= 5:
                error, status = "Πάρα πολλές αποτυχημένες προσπάθειες. Δοκιμάστε ξανά σε λίγα λεπτά.", 429
            elif check_password(request.form.get("password", ""), cfg):
                session.clear()  # νέο session μετά τη σύνδεση (αποφυγή session fixation)
                session["admin"], session.permanent = True, True
                return redirect(url_for("admin"))
            else:
                app.limiter.record(ip)
                error, status = "Ο κωδικός πρόσβασης δεν είναι σωστός.", 401
        if not session.get("admin"):
            return render_template("admin.html", business=cfg["BUSINESS_NAME"], login=True, error=error), status
        c = db()
        return render_template(
            "admin.html", business=cfg["BUSINESS_NAME"], login=False, error=request.args.get("e"),
            default_pw=not cfg["ADMIN_PASSWORD_HASH"] and cfg["ADMIN_PASSWORD"] in WEAK,
            bookings=c.execute(
                "select b.*, s.name sname, s.minutes from bookings b join services s on s.id=b.service_id "
                "where b.date>=? order by b.date, b.start", (now_local().date().isoformat(),)).fetchall(),
            services=c.execute("select * from services order by category, minutes, name").fetchall())

    @app.post("/admin/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.post("/admin/cancel/<int:bid>")
    @admin_only
    def cancel(bid):
        db().execute("delete from bookings where id=?", (bid,))
        return redirect(url_for("admin"))

    @app.post("/admin/service")
    @admin_only
    def add_service():
        try:
            name, mins = request.form["name"].strip(), int(request.form["minutes"])
            price, cat = float(request.form["price"]), request.form["category"]
            if not (name and len(name) <= 60 and 15 <= mins <= 480 and 0 <= price <= 10000 and cat in smartform.CATEGORIES):
                raise ValueError
            db().execute(ADD_SERVICE, (name, mins, price, cat))
        except (ValueError, KeyError):
            return redirect(url_for("admin", e="Παρακαλούμε ελέγξτε τα στοιχεία της υπηρεσίας."))
        return redirect(url_for("admin"))

    @app.post("/admin/service/<int:sid>/delete")
    @admin_only
    def del_service(sid):
        if db().execute("select 1 from bookings where service_id=?", (sid,)).fetchone():
            return redirect(url_for("admin", e="Υπάρχουν κρατήσεις για αυτή την υπηρεσία. Ακυρώστε τις πρώτα."))
        db().execute("delete from services where id=?", (sid,))
        return redirect(url_for("admin"))


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=flask_app.config["DEBUG"])
