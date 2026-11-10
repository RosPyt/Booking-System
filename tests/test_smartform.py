from datetime import date

import smartform

TODAY = date(2026, 11, 11)  # Τετάρτη
SERVICES = [
    {"id": 1, "name": "Κούρεμα", "minutes": 30, "category": "men"},
    {"id": 2, "name": "Γένια", "minutes": 30, "category": "men"},
    {"id": 3, "name": "Κούρεμα + γένια", "minutes": 60, "category": "men"},
    {"id": 4, "name": "Κούρεμα", "minutes": 45, "category": "women"},
    {"id": 5, "name": "Βαφή μαλλιών", "minutes": 90, "category": "women"},
]


def parse(text):
    return smartform.parse_request(text, SERVICES, TODAY)


def test_combo_service_wins_over_single():
    assert parse("κούρεμα και γένια την Πέμπτη το απόγευμα") == {
        "service_id": 3, "category": "men", "date": "2026-11-12", "part": "afternoon"}


def test_category_and_relative_days():
    r = parse("γυναικείο κούρεμα αύριο το πρωί")
    assert (r["service_id"], r["category"], r["date"], r["part"]) == (4, "women", "2026-11-12", "morning")
    assert parse("βαφή μεθαύριο")["date"] == "2026-11-13"
    assert parse("σήμερα")["date"] == "2026-11-11"


def test_same_weekday_means_next_week():
    assert parse("Τετάρτη")["date"] == "2026-11-18"


def test_unrecognised_text_gives_nulls():
    assert parse("asdf qwerty") == {"service_id": None, "category": None, "date": None, "part": None}


def test_sanitize_rejects_untrusted_model_output():
    bad = {"service_id": 999, "category": "<script>", "date": "2020-01-01", "part": "midnight"}
    assert smartform.sanitize(bad, SERVICES, TODAY) == {"service_id": None, "category": None, "date": None, "part": None}
    assert smartform.sanitize("not a dict", SERVICES, TODAY)["service_id"] is None
    assert smartform.sanitize({"service_id": True}, SERVICES, TODAY)["service_id"] is None


def test_sanitize_category_follows_service():
    r = smartform.sanitize({"service_id": 5, "category": "men"}, SERVICES, TODAY)
    assert r["category"] == "women"


def test_ai_failure_falls_back_to_rules(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API down")
    monkeypatch.setattr(smartform, "parse_ai", boom)
    r = smartform.parse_request("κούρεμα αύριο", SERVICES, TODAY, api_key="sk-x", model="m")
    assert r["service_id"] == 1 and r["date"] == "2026-11-12"


def test_parse_endpoint_and_rate_limit(client):
    r = client.post("/api/parse", json={"text": "κούρεμα αύριο"})
    assert r.status_code == 200 and r.get_json()["service_id"]
    assert client.post("/api/parse", data="junk", content_type="text/plain").status_code == 200
    codes = [client.post("/api/parse", json={"text": "x"}).status_code for _ in range(25)]
    assert 429 in codes


def test_ai_date_outside_window_is_dropped():
    far = {"service_id": 1, "date": "2027-06-01"}
    assert smartform.sanitize(far, SERVICES, TODAY, max_days=14)["date"] is None
    assert smartform.sanitize({"date": "2026-11-25"}, SERVICES, TODAY, max_days=14)["date"] == "2026-11-25"
    assert smartform.sanitize({"date": "2026-11-26"}, SERVICES, TODAY, max_days=14)["date"] is None
