import threading
from datetime import date, timedelta

from app import now_local
from tests.conftest import book


def slots(client, sid, day):
    return client.get(f"/api/slots?service={sid}&date={day}").get_json()["slots"]


def test_free_slots_cover_opening_hours(client, services, open_day):
    cut = services[("Κούρεμα", "men")]  # 30'
    s = slots(client, cut, open_day)
    assert s[0] == 9 * 60 and s[-1] == 17 * 60 + 30


def test_booking_blocks_overlapping_slots(client, services, open_day):
    cut, both = services[("Κούρεμα", "men")], services[("Κούρεμα + γένια", "men")]  # 30' και 60'
    assert book(client, both, open_day, 10 * 60).status_code == 201  # 10:00–11:00
    free = slots(client, cut, open_day)
    assert 10 * 60 not in free and 10 * 60 + 30 not in free
    assert 9 * 60 + 30 in free and 11 * 60 in free
    assert book(client, cut, open_day, 10 * 60 + 30).status_code == 409


def test_long_service_cannot_overlap_next_booking(client, services, open_day):
    cut, both = services[("Κούρεμα", "men")], services[("Κούρεμα + γένια", "men")]
    assert book(client, cut, open_day, 10 * 60).status_code == 201
    assert 9 * 60 + 30 not in slots(client, both, open_day)  # θα τελείωνε στις 10:30, μέσα στο ραντεβού των 10:00


def test_last_slot_ends_at_closing_time(client, services, open_day):
    color = services[("Βαφή μαλλιών", "women")]  # 90'
    assert slots(client, color, open_day)[-1] == 16 * 60 + 30


def test_no_slots_on_closed_day_or_past(client, services, app):
    cut = services[("Κούρεμα", "men")]
    with app.app_context():
        d = now_local().date()
    sunday = d + timedelta((6 - d.weekday()) % 7 or 7)
    assert slots(client, cut, sunday.isoformat()) == []
    assert slots(client, cut, (d - timedelta(days=1)).isoformat()) == []
    assert slots(client, cut, (d + timedelta(days=app.config["MAX_DAYS_AHEAD"] + 1)).isoformat()) == []
    assert slots(client, cut, "not-a-date") == []


def test_booking_validation(client, services, open_day):
    cut = services[("Κούρεμα", "men")]
    assert book(client, cut, open_day, 600, phone="abc").status_code == 400
    assert book(client, cut, open_day, 600, name="x").status_code == 400
    assert book(client, 9999, open_day, 600).status_code == 400
    assert book(client, cut, open_day, "10:00").status_code == 400
    assert book(client, cut, open_day, True).status_code == 400
    assert client.post("/api/book", data="junk", content_type="text/plain").status_code == 400
    assert client.post("/api/book", json=[1, 2]).status_code == 400
    assert book(client, cut, open_day, 601).status_code == 409  # ώρα εκτός πλέγματος


def test_unknown_service_slots_is_json_404(client):
    r = client.get("/api/slots?service=424242&date=2030-01-01")
    assert r.status_code == 404 and "error" in r.get_json()


def test_concurrent_bookings_never_double_book(app, services, open_day):
    cut = services[("Κούρεμα", "men")]
    codes = []

    def attempt(i):
        codes.append(book(app.test_client(), cut, open_day, 12 * 60, name=f"Πελάτης {i}").status_code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201] + [409] * 9


def test_default_window_is_two_weeks(app):
    assert app.config["MAX_DAYS_AHEAD"] == 14


def test_cannot_book_past_or_beyond_window(client, services, app):
    cut = services[("Κούρεμα", "men")]
    with app.app_context():
        today = now_local().date()
    for d in (date(2020, 11, 10), today - timedelta(days=1), today + timedelta(days=15), today + timedelta(days=365)):
        assert book(client, cut, d.isoformat(), 600).status_code == 409


def test_index_date_input_has_min_and_max(client, app):
    with app.app_context():
        today = now_local().date()
    html = client.get("/").get_data(as_text=True)
    assert f'min="{today}"' in html and f'max="{today + timedelta(days=14)}"' in html


def test_unknown_timezone_falls_back_instead_of_crashing(tmp_path):
    from app import create_app
    app = create_app({"TESTING": True, "SECRET_KEY": "k", "ADMIN_PASSWORD": "p" * 8,
                      "DB_PATH": str(tmp_path / "tz.db"), "TIMEZONE": "Mars/Olympus"})
    assert app.test_client().get("/").status_code == 200
