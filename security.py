"""Μικρά εργαλεία ασφαλείας: CSRF token, έλεγχος κωδικού, απλό rate limiting."""
import hmac
import secrets
import time
from collections import defaultdict, deque

from flask import abort, request, session
from werkzeug.security import check_password_hash


class RateLimiter:
    """Απλός in-memory περιορισμός αιτημάτων ανά κλειδί (π.χ. IP). Αρκεί για ένα instance."""

    def __init__(self):
        self._hits = defaultdict(deque)

    def recent(self, key, window):
        q, now = self._hits[key], time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if not q:
            self._hits.pop(key, None)
        return len(q)

    def record(self, key):
        self._hits[key].append(time.monotonic())

    def allow(self, key, limit, window):
        """Καταγράφει το αίτημα και επιστρέφει False αν ξεπεράστηκε το όριο."""
        if self.recent(key, window) >= limit:
            return False
        self.record(key)
        return True


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def verify_csrf():
    sent = request.form.get("csrf_token", "").encode()
    expected = session.get("csrf", "").encode()
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Η φόρμα έληξε. Ανανεώστε τη σελίδα και δοκιμάστε ξανά.")


def check_password(candidate, cfg):
    """Υποστηρίζει ADMIN_PASSWORD_HASH (προτιμάται) ή απλό ADMIN_PASSWORD."""
    if cfg.get("ADMIN_PASSWORD_HASH"):
        return check_password_hash(cfg["ADMIN_PASSWORD_HASH"], candidate)
    return hmac.compare_digest(candidate.encode(), cfg["ADMIN_PASSWORD"].encode())
