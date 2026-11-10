from tests.conftest import book, login


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert b'name="password"' in r.data
    assert client.post("/admin/cancel/1", data={}).status_code == 400  # χωρίς CSRF δεν περνά ούτε στο login


def test_wrong_password_rejected_then_rate_limited(client):
    for _ in range(5):
        r, _ = login(client, "wrong")
        assert r.status_code == 401
    r, _ = login(client, "s3cret-pass")  # ακόμα και ο σωστός κωδικός μπλοκάρεται προσωρινά
    assert r.status_code == 429


def test_login_and_dashboard(client):
    r, _ = login(client)
    assert r.status_code == 302
    page = client.get("/admin").get_data(as_text=True)
    assert "Πίνακας διαχείρισης" in page and "Κούρεμα" in page


def test_post_without_csrf_is_rejected(client, services, open_day):
    login(client)
    book(client, services[("Κούρεμα", "men")], open_day, 600)
    assert client.post("/admin/cancel/1", data={}).status_code == 400
    assert client.post("/admin/cancel/1", data={"csrf_token": "forged"}).status_code == 400


def test_cancel_booking_frees_the_slot(client, services, open_day):
    cut = services[("Κούρεμα", "men")]
    book(client, cut, open_day, 600)
    login(client)
    token = _csrf_from_dashboard(client)
    assert client.post("/admin/cancel/1", data={"csrf_token": token}).status_code == 302
    assert book(client, cut, open_day, 600).status_code == 201


def test_service_crud_and_guard(client, services, open_day):
    login(client)
    token = _csrf_from_dashboard(client)
    ok = {"csrf_token": token, "name": "Ξύρισμα", "minutes": "30", "price": "10", "category": "men"}
    assert "Ξύρισμα" in _follow(client, "/admin/service", ok)
    for bad in ({"minutes": "5"}, {"price": "-1"}, {"price": "nan"}, {"category": "kids"}, {"name": "  "}):
        assert "Παρακαλούμε ελέγξτε" in _follow(client, "/admin/service", {**ok, **bad})
    # δεν διαγράφεται υπηρεσία με κρατήσεις
    cut = services[("Κούρεμα", "men")]
    book(client, cut, open_day, 600)
    assert "Υπάρχουν κρατήσεις" in _follow(client, f"/admin/service/{cut}/delete", {"csrf_token": token})


def test_logout_clears_session(client):
    login(client)
    token = _csrf_from_dashboard(client)
    client.post("/admin/logout", data={"csrf_token": token})
    assert b'name="password"' in client.get("/admin").data


def _csrf_from_dashboard(client):
    import re
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin").get_data(as_text=True)).group(1)


def _follow(client, url, data):
    return client.post(url, data=data, follow_redirects=True).get_data(as_text=True)
