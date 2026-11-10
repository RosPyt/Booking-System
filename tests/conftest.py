import re
from datetime import timedelta

import pytest

from app import create_app, now_local


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True, "SECRET_KEY": "test-secret", "ADMIN_PASSWORD": "s3cret-pass",
        "DB_PATH": str(tmp_path / "test.db"), "ANTHROPIC_API_KEY": "",
        "OPEN_HOUR": 9, "CLOSE_HOUR": 18, "CLOSED_DAYS": {6},
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def open_day(app):
    """Η πρώτη επόμενη μέρα που το κατάστημα είναι ανοιχτό (ISO string)."""
    with app.app_context():
        d = now_local().date() + timedelta(days=1)
        while d.weekday() in app.config["CLOSED_DAYS"]:
            d += timedelta(days=1)
        return d.isoformat()


@pytest.fixture
def services(client):
    """όνομα+κατηγορία -> id, όπως μπήκαν από το seed."""
    out = {}
    with client.application.app_context():
        from app import db
        for r in db().execute("select id,name,category,minutes from services"):
            out[(r["name"], r["category"])] = r["id"]
    return out


def book(client, service_id, day, start, name="Γιώργος", phone="6900000000"):
    return client.post("/api/book", json={"service_id": service_id, "date": day, "start": start,
                                          "name": name, "phone": phone})


def login(client, password="s3cret-pass"):
    page = client.get("/admin").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    return client.post("/admin", data={"password": password, "csrf_token": token}), token
