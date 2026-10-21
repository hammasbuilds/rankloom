"""The Rankloom web server: one page app, a JSON API, accounts, tool runs and analytics.

Standard library only. Run with `python -m rankloom.server --port 8130`.

Security decisions, in one place:
- Sessions are random 256-bit tokens in an HttpOnly, SameSite=Lax cookie; only their SHA-256 is
  stored, so a copied database cannot be replayed as a login.
- Every state-changing request must carry the `X-Rankloom: 1` header and, when the browser sends
  one, a matching Origin. A cross-site form cannot set a custom header, which closes CSRF without
  a token round trip.
- Login, 2-step, registration and reset requests are rate limited per address and per account.
- A password change ends every other session; a reset ends all of them.
- Links in email are built from RANKLOOM_BASE_URL, never from the request's Host header, so a
  forged Host cannot turn a reset email into a link to someone else's server.
- The pages ship a strict Content-Security-Policy: scripts and styles from this origin only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import ai, github, jobradar_link, mail, security, sources
from .db import Database, now
from .engines import ENGINES, search_perf
from .engines.common import Context, InputProblem
from .netguard import FetchFailed, FetchRefused, safe_fetch
from .tools import BY_SLUG, find, public_catalog
from .tools import status as tool_status

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
COOKIE = "rl_session"
SESSION_TTL = 14 * 86400
PENDING_TTL = 10 * 60
RESET_TTL = 3600
MAX_BODY = 64 * 1024
MAX_UPLOAD = 12 * 1024 * 1024  # a Search Console zip or a lead CSV, base64-encoded
LEAD_STATUSES = ["new", "contacted", "replied", "won", "lost"]
RUN_ERRORS = (FetchRefused, FetchFailed, InputProblem, ai.AIUnavailable, sources.SourceFailed)
LEAD_COLUMNS = {
    "name": ("name", "business", "business name", "company", "title"),
    "website": ("website", "site", "url", "web", "domain"),
    "phone": ("phone", "telephone", "phone number", "mobile", "contact number"),
    "email": ("email", "e-mail", "email address"),
    "address": ("address", "street", "full address", "location"),
    "city": ("city", "town"),
    "category": ("category", "type", "trade", "industry"),
    "status": ("status", "stage"),
    "notes": ("notes", "note", "comments"),
    "score": ("score", "opportunity"),
    "problems": ("problems", "issues"),
}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: "
    "https://avatars.githubusercontent.com; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)

# (limit, window seconds) per bucket family
LIMITS = {
    "login-ip": (20, 900),
    "login-email": (8, 900),
    "mfa": (6, 300),
    "register-ip": (10, 3600),
    "forgot-ip": (5, 3600),
    "run-user": (30, 600),
    "github-user": (60, 600),
    "reauth-user": (6, 900),
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class App:
    def __init__(
        self,
        data_dir: Path | str,
        base_url: str,
        secure_cookies: bool = False,
        db_path: str | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(db_path or self.data_dir / "rankloom.db")
        self.box = security.SealedBox(self._app_key())
        self.base_url = base_url.rstrip("/")
        self.secure_cookies = secure_cookies
        self.fetch = safe_fetch  # replaced in tests and in the offline browser walk
        self.crawler = jobradar_link.Crawler(self.data_dir)

    def _app_key(self) -> bytes:
        env = os.environ.get("RANKLOOM_SECRET", "")
        if env:
            return hashlib.sha256(env.encode()).digest()
        path = self.data_dir / "app.key"
        if not path.exists():
            path.write_bytes(secrets.token_bytes(32))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return path.read_bytes()

    # --- rate limiting ----------------------------------------------------------------------

    def limited(self, family: str, key: str) -> bool:
        limit, window = LIMITS[family]
        bucket = f"{family}:{key}"
        t = now()
        self.db.run("DELETE FROM attempts WHERE at < ?", t - 86400)
        count = self.db.one(
            "SELECT COUNT(*) FROM attempts WHERE bucket = ? AND at > ?", bucket, t - window
        )[0]
        if count >= limit:
            return True
        self.db.run("INSERT INTO attempts (bucket, at) VALUES (?, ?)", bucket, t)
        return False

    def clear_limit(self, family: str, key: str) -> None:
        self.db.run("DELETE FROM attempts WHERE bucket = ?", f"{family}:{key}")

    def forgive_one(self, family: str, key: str) -> None:
        """Take back the attempt just counted: a correct sign-in is not an attack, and an office
        behind one address must not lock itself out by signing in."""
        self.db.run(
            "DELETE FROM attempts WHERE rowid = (SELECT MAX(rowid) FROM attempts WHERE bucket = ?)",
            f"{family}:{key}",
        )

    # --- sessions -----------------------------------------------------------------------------

    def create_session(self, user_id: int, ua: str, ip: str, mfa_pending: bool) -> str:
        token = security.new_token()
        t = now()
        ttl = PENDING_TTL if mfa_pending else SESSION_TTL
        self.db.run(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, "
            "mfa_pending, user_agent, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            security.token_hash(token),
            user_id,
            t,
            t + ttl,
            t,
            int(mfa_pending),
            ua[:200],
            ip,
        )
        return token

    def session(self, token: str | None):
        if not token:
            return None
        row = self.db.one(
            "SELECT s.*, u.email, u.name, u.totp_secret IS NOT NULL AS totp_on, u.github_login "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            security.token_hash(token),
        )
        if row is None:
            return None
        t = now()
        if row["expires_at"] < t:
            self.db.run("DELETE FROM sessions WHERE token_hash = ?", row["token_hash"])
            return None
        if t - row["last_seen"] > 60:
            self.db.run(
                "UPDATE sessions SET last_seen = ? WHERE token_hash = ?", t, row["token_hash"]
            )
        return row

    def cookie(self, token: str, max_age: int) -> str:
        parts = [f"{COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if self.secure_cookies:
            parts.append("Secure")
        return "; ".join(parts)


def _csv_safe(value) -> str:
    """A cell a spreadsheet will not run: leading = + - @ start a formula in Excel."""
    v = "" if value is None else str(value)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _csv_unsafe(value: str) -> str:
    """Undo _csv_safe on the way back in, so an exported file re-imports as it left."""
    return value[1:] if value[:1] == "'" and value[1:2] in ("=", "+", "-", "@", "\t", "\r") else value


def import_leads(db, user_id: int, text: str) -> tuple[int, int]:
    from .engines.leads import opportunity, save_lead

    text = text.lstrip("\ufeff")
    if not text.strip():
        raise InputProblem("The file is empty.")
    reader = csv.DictReader(io.StringIO(text))
    header = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    cols = {
        field: next((header[a] for a in aliases if a in header), None)
        for field, aliases in LEAD_COLUMNS.items()
    }
    if not cols["name"]:
        raise InputProblem("The CSV needs a name (or business) column.")
    added = skipped = 0
    for row in reader:
        lead = {k: _csv_unsafe(str(row.get(c) or "").strip()) for k, c in cols.items() if c}
        if not lead.get("name"):
            skipped += 1
            continue
        lead["source"] = lead.get("source") or "CSV import"
        problems = [p.strip() for p in lead.pop("problems", "").split(";") if p.strip()]
        lead["problems"] = problems or ([] if lead.get("website") else ["no website listed"])
        score = lead.pop("score", "")
        # The same rule as a searched lead: no website listed is a lead to check, not proof.
        lead["opportunity"] = (
            max(0, min(100, int(score))) if score.isdigit()
            else None if lead.get("website") else opportunity({})
        )
        status = lead.pop("status", "").lower()
        notes = lead.pop("notes", "")
        lead_id = save_lead(db, user_id, lead)
        if status in LEAD_STATUSES or notes:
            db.run(
                "UPDATE leads SET status = CASE WHEN ? != '' THEN ? ELSE status END, "
                "notes = CASE WHEN ? != '' THEN ? ELSE notes END WHERE id = ? AND user_id = ?",
                status if status in LEAD_STATUSES else "",
                status,
                notes[:4000],
                notes[:4000],
                lead_id,
                user_id,
            )
        added += 1
        if added >= 5000:
            break
    return added, skipped


def user_view(s) -> dict:
    return {
        "id": s["user_id"],
        "email": s["email"],
        "name": s["name"],
        "two_factor": bool(s["totp_on"]),
        "github": s["github_login"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Rankloom"
    sys_version = ""
    app: App

    # --- plumbing -------------------------------------------------------------------------------

    def log_message(self, fmt, *args):  # quieter than the default; never logs bodies
        if os.environ.get("RANKLOOM_QUIET"):
            return
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    @property
    def ip(self) -> str:
        return self.client_address[0]

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed cookie header is just "no session"
            return None
        morsel = jar.get(COOKIE)
        return morsel.value if morsel else None

    def _headers_common(self, cache: str = "no-store"):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", cache)

    def send_json(self, status: int, payload, cookies: list[str] | None = None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for c in cookies or []:
            self.send_header("Set-Cookie", c)
        self._headers_common()
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self._headers_common()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_static(self, rel: str):
        path = (STATIC / rel).resolve()
        if not path.is_relative_to(STATIC) or not path.is_file():
            path = STATIC / "index.html"
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        if path.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._headers_common("no-cache")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> None:
        """Read the whole body before anything can refuse the request. A reply sent while the
        client is still sending makes Windows reset the connection, and the client then sees a
        reset instead of the 403 or 413 it was given."""
        try:
            length = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError as exc:
            raise ApiError(400, "Bad Content-Length.") from exc
        if length > MAX_UPLOAD:
            self.close_connection = True
            raise ApiError(413, "The request is too large.")
        self._raw = self.rfile.read(length) if length else b""

    def body(self, limit: int = MAX_BODY) -> dict:
        raw = getattr(self, "_raw", b"")
        if len(raw) > limit:
            raise ApiError(413, "The request is too large.")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ApiError(400, "The request body is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError(400, "The request body must be a JSON object.")
        return data

    def check_csrf(self):
        if self.headers.get("X-Rankloom") != "1":
            raise ApiError(403, "Missing request header.")
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if urlsplit(origin).netloc != host:
                raise ApiError(403, "Cross-site request refused.")

    def need_session(self, allow_pending: bool = False):
        s = self.app.session(self._token())
        if s is None:
            raise ApiError(401, "Sign in first.")
        if s["mfa_pending"] and not allow_pending:
            raise ApiError(401, "Finish 2-step verification first.", mfa_required=True)
        return s

    # --- dispatch -------------------------------------------------------------------------------

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_HEAD(self):
        self.send_response(405)
        self.end_headers()

    def _dispatch(self, method: str):
        self._raw = b""
        url = urlsplit(self.path)
        path = url.path
        try:
            if method == "GET" and path == "/auth/github/callback":
                return self.github_callback(parse_qs(url.query))
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(405, "Method not allowed.")
                rel = path.lstrip("/")
                if rel.startswith("static/"):
                    return self.send_static(rel[len("static/") :])
                return self.send_static("index.html")
            if method == "POST":
                self.read_body()
                self.check_csrf()
            route = ROUTES.get((method, path))
            if route is not None:
                return route(self)
            for (m, pattern), fn in PATTERN_ROUTES:
                match = pattern.fullmatch(path)
                if m == method and match:
                    return fn(self, *match.groups())
            raise ApiError(404, "No such endpoint.")
        except ApiError as exc:
            self.send_json(exc.status, {"error": exc.message, **exc.extra})
        except Exception:  # noqa: BLE001 - never leak a traceback to the client
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on the server."})

    # --- auth -----------------------------------------------------------------------------------

    def me(self):
        s = self.app.session(self._token())
        if s is None:
            raise ApiError(401, "Signed out.")
        if s["mfa_pending"]:
            return self.send_json(200, {"user": None, "mfa_required": True})
        return self.send_json(200, {"user": user_view(s)})

    def register(self):
        if self.app.limited("register-ip", self.ip):
            raise ApiError(429, "Too many sign-ups from this address. Try again later.")
        b = self.body()
        name = str(b.get("name", "")).strip()[:80]
        email = str(b.get("email", "")).strip().lower()
        password = str(b.get("password", ""))
        if not name:
            raise ApiError(400, "Enter your name.", field="name")
        if not EMAIL_RE.match(email):
            raise ApiError(400, "Enter a valid email address.", field="email")
        problem = security.password_problem(password, email)
        if problem:
            raise ApiError(400, problem, field="password")
        if self.app.db.one("SELECT 1 FROM users WHERE email = ?", email):
            raise ApiError(
                409, "An account with that email already exists. Sign in instead.", field="email"
            )
        cur = self.app.db.run(
            "INSERT INTO users (email, name, pw_hash, created_at) VALUES (?, ?, ?, ?)",
            email,
            name,
            security.hash_password(password),
            now(),
        )
        token = self.app.create_session(
            cur.lastrowid, self.headers.get("User-Agent", ""), self.ip, False
        )
        self.send_json(201, {"ok": True}, [self.app.cookie(token, SESSION_TTL)])

    _DUMMY_HASH = security.hash_password("rankloom-timing-equaliser")

    def login(self):
        b = self.body()
        email = str(b.get("email", "")).strip().lower()
        password = str(b.get("password", ""))
        if self.app.limited("login-ip", self.ip) or self.app.limited("login-email", email):
            raise ApiError(429, "Too many sign-in attempts. Wait 15 minutes and try again.")
        user = self.app.db.one("SELECT * FROM users WHERE email = ?", email)
        if user is None:
            security.verify_password(password, self._DUMMY_HASH)  # same cost either way
            raise ApiError(401, "That email and password do not match.")
        if not security.verify_password(password, user["pw_hash"]):
            raise ApiError(401, "That email and password do not match.")
        self.app.clear_limit("login-email", email)
        self.app.forgive_one("login-ip", self.ip)
        old = self._token()
        if old:
            self.app.db.run("DELETE FROM sessions WHERE token_hash = ?", security.token_hash(old))
        pending = user["totp_secret"] is not None
        token = self.app.create_session(
            user["id"], self.headers.get("User-Agent", ""), self.ip, pending
        )
        ttl = PENDING_TTL if pending else SESSION_TTL
        self.send_json(200, {"mfa_required": pending}, [self.app.cookie(token, ttl)])

    def two_factor_login(self):
        s = self.need_session(allow_pending=True)
        if not s["mfa_pending"]:
            return self.send_json(200, {"ok": True})
        if self.app.limited("mfa", s["token_hash"]):
            raise ApiError(429, "Too many codes tried. Sign in again in a few minutes.")
        code = str(self.body().get("code", "")).strip()
        user = self.app.db.one("SELECT * FROM users WHERE id = ?", s["user_id"])
        ok = False
        if code.replace("-", "").replace(" ", "").isdigit():
            secret = self.app.box.open(user["totp_secret"])
            step = security.verify_totp(secret, code, user["totp_last_step"])
            if step is not None:
                self.app.db.run(
                    "UPDATE users SET totp_last_step = ? WHERE id = ?", step, user["id"]
                )
                ok = True
        else:
            codes = json.loads(user["recovery_codes"])
            h = security.recovery_hash(code)
            if h in codes:
                codes.remove(h)
                self.app.db.run(
                    "UPDATE users SET recovery_codes = ? WHERE id = ?",
                    json.dumps(codes),
                    user["id"],
                )
                ok = True
        if not ok:
            raise ApiError(
                401,
                "That code is not right. Use the current code from your app, "
                "or one of your recovery codes.",
            )
        # Promote by replacing the session, so the pending token can never become a full one.
        self.app.db.run("DELETE FROM sessions WHERE token_hash = ?", s["token_hash"])
        token = self.app.create_session(
            s["user_id"], self.headers.get("User-Agent", ""), self.ip, False
        )
        self.send_json(200, {"ok": True}, [self.app.cookie(token, SESSION_TTL)])

    def logout(self):
        token = self._token()
        if token:
            self.app.db.run("DELETE FROM sessions WHERE token_hash = ?", security.token_hash(token))
        self.send_json(200, {"ok": True}, [self.app.cookie("", 0)])

    def forgot(self):
        if self.app.limited("forgot-ip", self.ip):
            raise ApiError(429, "Too many reset requests. Try again in an hour.")
        email = str(self.body().get("email", "")).strip().lower()
        user = self.app.db.one("SELECT id, email FROM users WHERE email = ?", email)
        delivery = "smtp" if mail.smtp_configured() else "outbox"
        if user is not None:
            token = security.new_token()
            self.app.db.run(
                "INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                security.token_hash(token),
                user["id"],
                now() + RESET_TTL,
            )
            link = f"{self.app.base_url}/reset?token={token}"
            delivery = mail.send(
                self.app.db,
                user["email"],
                "Reset your Rankloom password",
                f"Someone asked to reset the password for this Rankloom account.\n\n"
                f"Set a new password here (the link works for one hour, once):\n{link}\n\n"
                f"If it was not you, ignore this message; your password has not changed.",
            )
        # Same answer whether or not the account exists, so the form cannot list accounts.
        self.send_json(200, {"ok": True, "delivery": delivery})

    def reset(self):
        b = self.body()
        token = str(b.get("token", ""))
        password = str(b.get("password", ""))
        row = self.app.db.one(
            "SELECT r.*, u.email FROM reset_tokens r JOIN users u ON u.id = r.user_id "
            "WHERE r.token_hash = ?",
            security.token_hash(token),
        )
        if row is None or row["used"] or row["expires_at"] < now():
            raise ApiError(
                400, "This reset link has expired or was already used. Ask for a new one."
            )
        problem = security.password_problem(password, row["email"])
        if problem:
            raise ApiError(400, problem, field="password")
        self.app.db.run(
            "UPDATE users SET pw_hash = ? WHERE id = ?",
            security.hash_password(password),
            row["user_id"],
        )
        self.app.db.run("UPDATE reset_tokens SET used = 1 WHERE user_id = ?", row["user_id"])
        self.app.db.run("DELETE FROM sessions WHERE user_id = ?", row["user_id"])
        self.send_json(200, {"ok": True})

    # --- account --------------------------------------------------------------------------------

    def change_password(self):
        s = self.need_session()
        b = self.body()
        if self.app.limited("reauth-user", str(s["user_id"])):
            raise ApiError(429, "Too many tries. Wait a few minutes and try again.")
        user = self.app.db.one("SELECT * FROM users WHERE id = ?", s["user_id"])
        if not security.verify_password(str(b.get("current", "")), user["pw_hash"]):
            raise ApiError(400, "Your current password is not right.", field="current")
        self.app.clear_limit("reauth-user", str(s["user_id"]))
        new = str(b.get("new", ""))
        problem = security.password_problem(new, user["email"])
        if problem:
            raise ApiError(400, problem, field="new")
        if security.verify_password(new, user["pw_hash"]):
            raise ApiError(400, "Choose a password different from the current one.", field="new")
        self.app.db.run(
            "UPDATE users SET pw_hash = ? WHERE id = ?", security.hash_password(new), user["id"]
        )
        ended = self.app.db.run(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            user["id"],
            s["token_hash"],
        ).rowcount
        self.send_json(200, {"ok": True, "other_sessions_ended": ended})

    def profile(self):
        s = self.need_session()
        name = str(self.body().get("name", "")).strip()[:80]
        if not name:
            raise ApiError(400, "Enter your name.", field="name")
        self.app.db.run("UPDATE users SET name = ? WHERE id = ?", name, s["user_id"])
        self.send_json(200, {"ok": True})

    def sessions(self):
        s = self.need_session()
        rows = self.app.db.all(
            "SELECT token_hash, created_at, last_seen, user_agent, ip FROM sessions "
            "WHERE user_id = ? AND mfa_pending = 0 ORDER BY last_seen DESC",
            s["user_id"],
        )
        self.send_json(
            200,
            {
                "sessions": [
                    {
                        "id": r["token_hash"][:16],
                        "current": r["token_hash"] == s["token_hash"],
                        "created_at": r["created_at"],
                        "last_seen": r["last_seen"],
                        "device": r["user_agent"],
                        "ip": r["ip"],
                    }
                    for r in rows
                ]
            },
        )

    def revoke_session(self):
        s = self.need_session()
        sid = str(self.body().get("id", ""))
        if sid == "others":
            n = self.app.db.run(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                s["user_id"],
                s["token_hash"],
            ).rowcount
            return self.send_json(200, {"ok": True, "ended": n})
        if not re.fullmatch(r"[0-9a-f]{16}", sid):
            raise ApiError(400, "Unknown session.")
        n = self.app.db.run(
            "DELETE FROM sessions WHERE user_id = ? AND substr(token_hash, 1, 16) = ? "
            "AND token_hash != ?",
            s["user_id"],
            sid,
            s["token_hash"],
        ).rowcount
        self.send_json(200, {"ok": True, "ended": n})

    # --- 2-step verification setup --------------------------------------------------------------

    def tfa_setup(self):
        s = self.need_session()
        if s["totp_on"]:
            raise ApiError(409, "2-step verification is already on.")
        secret = security.new_totp_secret()
        self.app.db.run(
            "UPDATE users SET totp_pending = ? WHERE id = ?",
            self.app.box.seal(secret),
            s["user_id"],
        )
        self.send_json(200, {"secret": secret, "uri": security.otpauth_uri(secret, s["email"])})

    def tfa_enable(self):
        s = self.need_session()
        user = self.app.db.one("SELECT * FROM users WHERE id = ?", s["user_id"])
        if user["totp_pending"] is None:
            raise ApiError(400, "Start the setup first.")
        secret = self.app.box.open(user["totp_pending"])
        step = security.verify_totp(secret, str(self.body().get("code", "")))
        if step is None:
            raise ApiError(
                400,
                "That code does not match. Check the time on your phone and try the newest code.",
                field="code",
            )
        codes = security.new_recovery_codes()
        self.app.db.run(
            "UPDATE users SET totp_secret = totp_pending, totp_pending = NULL, totp_last_step = ?,"
            " recovery_codes = ? WHERE id = ?",
            step,
            json.dumps([security.recovery_hash(c) for c in codes]),
            user["id"],
        )
        self.send_json(200, {"ok": True, "recovery_codes": codes})

    def _password_and_code(self, s, b) -> dict:
        """Re-check the password, and the authenticator code when 2-step is on.

        Both are checked here, not by each caller: making new recovery codes once checked
        only the password, so a stolen session plus the password minted permanent bypass codes.
        """
        if self.app.limited("reauth-user", str(s["user_id"])):
            raise ApiError(429, "Too many tries. Wait a few minutes and try again.")
        user = self.app.db.one("SELECT * FROM users WHERE id = ?", s["user_id"])
        if not security.verify_password(str(b.get("password", "")), user["pw_hash"]):
            raise ApiError(400, "Your password is not right.", field="password")
        if user["totp_secret"] is not None:
            secret = self.app.box.open(user["totp_secret"])
            step = security.verify_totp(secret, str(b.get("code", "")), user["totp_last_step"])
            if step is None:
                raise ApiError(400, "That code does not match.", field="code")
            self.app.db.run("UPDATE users SET totp_last_step = ? WHERE id = ?", step, user["id"])
        self.app.clear_limit("reauth-user", str(s["user_id"]))
        return user

    def tfa_disable(self):
        s = self.need_session()
        b = self.body()
        user = self._password_and_code(s, b)
        if user["totp_secret"] is None:
            raise ApiError(409, "2-step verification is already off.")
        self.app.db.run(
            "UPDATE users SET totp_secret = NULL, totp_pending = NULL, recovery_codes = '[]', "
            "totp_last_step = 0 WHERE id = ?",
            user["id"],
        )
        self.send_json(200, {"ok": True})

    def tfa_recovery(self):
        s = self.need_session()
        user = self._password_and_code(s, self.body())
        if user["totp_secret"] is None:
            raise ApiError(409, "Turn on 2-step verification first.")
        codes = security.new_recovery_codes()
        self.app.db.run(
            "UPDATE users SET recovery_codes = ? WHERE id = ?",
            json.dumps([security.recovery_hash(c) for c in codes]),
            user["id"],
        )
        self.send_json(200, {"ok": True, "recovery_codes": codes})

    def tfa_status(self):
        s = self.need_session()
        user = self.app.db.one("SELECT recovery_codes FROM users WHERE id = ?", s["user_id"])
        self.send_json(
            200,
            {
                "enabled": bool(s["totp_on"]),
                "recovery_left": len(json.loads(user["recovery_codes"])),
            },
        )

    # --- tools, runs, analytics -----------------------------------------------------------------

    def tools(self):
        self.need_session()
        self.send_json(200, {"tools": public_catalog(), "ai": ai.engine() is not None})

    def event(self):
        s = self.need_session()
        b = self.body()
        tool, sub = str(b.get("tool", "")), str(b.get("subtool", ""))
        if tool not in BY_SLUG or b.get("kind") != "open" or (sub and not find(tool, sub)):
            raise ApiError(400, "Unknown tool or event.")
        recent = self.app.db.one(
            "SELECT 1 FROM events WHERE user_id = ? AND tool = ? AND subtool = ? AND "
            "kind = 'open' AND at > ?",
            s["user_id"],
            tool,
            sub,
            now() - 30,
        )
        if not recent:  # a reload storm is one visit, not twenty
            self.app.db.run(
                "INSERT INTO events (user_id, tool, subtool, kind, at) VALUES (?, ?, ?, 'open', ?)",
                s["user_id"],
                tool,
                sub,
                now(),
            )
        self.send_json(200, {"ok": True})

    @staticmethod
    def _clean_fields(sub: dict, raw: dict) -> dict:
        out: dict = {}
        for f in sub["fields"]:
            v = raw.get(f["name"])
            if v is None:
                continue
            if f["type"] == "file":
                if not isinstance(v, list):
                    raise ApiError(400, "Files must be a list.")
                out[f["name"]] = [
                    {"name": str(x.get("name", ""))[:200], "data": str(x.get("data", ""))}
                    for x in v[:10]
                    if isinstance(x, dict)
                ]
            elif f["type"] == "textarea":
                out[f["name"]] = str(v)[:40_000]
            else:
                out[f["name"]] = str(v)[:500]
        return out

    def run_tool(self, slug: str, subslug: str):
        s = self.need_session()
        hit = find(slug, subslug)
        if hit is None:
            raise ApiError(404, "No such tool.")
        tool, sub = hit
        engine = ENGINES.get(f"{slug}/{subslug}")
        if engine is None:
            raise ApiError(409, f"{sub['name']} is a page, not something to run.")
        if tool_status(sub) == "needs-ai":
            raise ApiError(409, ai.SETUP_HINT, needs_ai=True)
        if self.app.limited("run-user", str(s["user_id"])):
            raise ApiError(429, "That is a lot of runs in ten minutes. Wait a little.")
        has_file = any(f["type"] == "file" for f in sub["fields"])
        raw = self.body(limit=MAX_UPLOAD if has_file else MAX_BODY).get("fields", {})
        if not isinstance(raw, dict):
            raise ApiError(400, "Fields must be an object.")
        fields = self._clean_fields(sub, raw)
        missing = [
            f["label"] for f in sub["fields"] if f.get("required") and not fields.get(f["name"])
        ]
        if missing:
            raise ApiError(400, f"Fill in: {', '.join(missing)}.")
        started = time.monotonic()
        ctx = Context(s["user_id"], self.app.db, self.app.fetch)
        try:
            summary, score, output = engine(fields, ctx)
            status = "ok"
        except RUN_ERRORS as exc:
            summary, score, output, status = str(exc), None, {"error": str(exc)}, "error"
        ms = int((time.monotonic() - started) * 1000)
        stored_input = {
            k: (f"{len(v)} file(s)" if isinstance(v, list) else v) for k, v in fields.items()
        }
        cur = self.app.db.run(
            "INSERT INTO runs (user_id, tool, subtool, created_at, status, duration_ms, summary, "
            "score, input_json, output_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            s["user_id"],
            slug,
            subslug,
            now(),
            status,
            ms,
            summary[:300],
            score,
            json.dumps(stored_input),
            json.dumps(output),
        )
        self.app.db.run(
            "INSERT INTO events (user_id, tool, subtool, kind, at) VALUES (?, ?, ?, 'run', ?)",
            s["user_id"],
            slug,
            subslug,
            now(),
        )
        self.send_json(
            200 if status == "ok" else 422,
            {
                "id": cur.lastrowid,
                "tool": slug,
                "subtool": subslug,
                "status": status,
                "summary": summary,
                "score": score,
                "duration_ms": ms,
                "output": output,
                "created_at": now(),
                **({"error": summary} if status == "error" else {}),
            },
        )

    def tool_runs(self, slug: str):
        s = self.need_session()
        if slug not in BY_SLUG:
            raise ApiError(404, "No such tool.")
        rows = self.app.db.all(
            "SELECT id, subtool, created_at, status, duration_ms, summary, score FROM runs "
            "WHERE user_id = ? AND tool = ? ORDER BY id DESC LIMIT 50",
            s["user_id"],
            slug,
        )
        self.send_json(200, {"runs": [dict(r) for r in rows]})

    def run_detail(self, rid: str):
        s = self.need_session()
        r = self.app.db.one(
            "SELECT * FROM runs WHERE id = ? AND user_id = ?", int(rid), s["user_id"]
        )
        if r is None:
            raise ApiError(404, "No such run.")
        self.send_json(
            200,
            {
                **{
                    k: r[k]
                    for k in (
                        "id",
                        "tool",
                        "subtool",
                        "created_at",
                        "status",
                        "duration_ms",
                        "summary",
                        "score",
                    )
                },
                "input": json.loads(r["input_json"]),
                "output": json.loads(r["output_json"]),
            },
        )

    def _daily(self, user_id: int, tool: str | None, days: int = 14) -> list[dict]:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        sql = "SELECT kind, at FROM events WHERE user_id = ? AND at >= ?"
        args: list = [user_id, int(start.timestamp())]
        if tool:
            sql += " AND tool = ?"
            args.append(tool)
        series = {
            (start + timedelta(days=i)).date().isoformat(): {"opens": 0, "runs": 0}
            for i in range(days)
        }
        for row in self.app.db.all(sql, *args):
            day = datetime.fromtimestamp(row["at"]).date().isoformat()
            if day in series:
                series[day]["opens" if row["kind"] == "open" else "runs"] += 1
        return [{"day": d, **v} for d, v in series.items()]

    def tool_stats(self, slug: str):
        s = self.need_session()
        tool = BY_SLUG.get(slug)
        if tool is None:
            raise ApiError(404, "No such tool.")
        uid = s["user_id"]
        opens = self.app.db.one(
            "SELECT COUNT(*) FROM events WHERE user_id = ? AND tool = ? AND kind = 'open'",
            uid,
            slug,
        )[0]
        agg = self.app.db.one(
            "SELECT COUNT(*) AS runs, SUM(status = 'ok') AS ok, SUM(status = 'error') AS errors, "
            "AVG(duration_ms) AS avg_ms, MAX(created_at) AS last_run FROM runs "
            "WHERE user_id = ? AND tool = ?",
            uid,
            slug,
        )
        per_sub = {
            r["subtool"]: r
            for r in self.app.db.all(
                "SELECT subtool, COUNT(*) AS runs, SUM(status = 'ok') AS ok, "
                "AVG(score) AS avg_score, "
                "MAX(created_at) AS last FROM runs WHERE user_id = ? AND tool = ? GROUP BY subtool",
                uid,
                slug,
            )
        }
        subs = []
        for sub in tool["subtools"]:
            r = per_sub.get(sub["slug"])
            subs.append(
                {
                    "slug": sub["slug"],
                    "name": sub["name"],
                    "runs": r["runs"] if r else 0,
                    "ok": (r["ok"] or 0) if r else 0,
                    "avg_score": round(r["avg_score"])
                    if r and r["avg_score"] is not None
                    else None,
                    "last": r["last"] if r else None,
                }
            )
        scores = self.app.db.all(
            "SELECT subtool, created_at, score, summary FROM runs WHERE user_id = ? AND tool = ? "
            "AND score IS NOT NULL ORDER BY id DESC LIMIT 20",
            uid,
            slug,
        )
        self.send_json(
            200,
            {
                "opens": opens,
                "runs": agg["runs"] or 0,
                "ok": agg["ok"] or 0,
                "errors": agg["errors"] or 0,
                "avg_ms": round(agg["avg_ms"]) if agg["avg_ms"] is not None else None,
                "last_run": agg["last_run"],
                "subtools": subs,
                "daily": self._daily(uid, slug),
                "scores": [dict(r) for r in reversed(scores)],
            },
        )

    def dashboard(self):
        s = self.need_session()
        uid = s["user_id"]
        catalog = public_catalog()
        per = {
            t["slug"]: {
                "slug": t["slug"],
                "name": t["name"],
                "subtools": len(t["subtools"]),
                "opens": 0,
                "runs": 0,
                "last": None,
            }
            for t in catalog
        }
        for r in self.app.db.all(
            "SELECT tool, kind, COUNT(*) AS n, MAX(at) AS last FROM events "
            "WHERE user_id = ? GROUP BY tool, kind",
            uid,
        ):
            if r["tool"] in per:
                per[r["tool"]]["opens" if r["kind"] == "open" else "runs"] = r["n"]
                per[r["tool"]]["last"] = max(per[r["tool"]]["last"] or 0, r["last"])
        recent = self.app.db.all(
            "SELECT id, tool, subtool, created_at, status, summary, score "
            "FROM runs WHERE user_id = ? ORDER BY id DESC LIMIT 8",
            uid,
        )
        count = lambda sql: self.app.db.one(sql, uid)[0]  # noqa: E731
        self.send_json(
            200,
            {
                "tools": list(per.values()),
                "daily": self._daily(uid, None),
                "recent": [dict(r) for r in recent],
                "imports": count("SELECT COUNT(*) FROM imports WHERE user_id = ?"),
                "leads": count("SELECT COUNT(*) FROM leads WHERE user_id = ?"),
                "clients": count("SELECT COUNT(*) FROM clients WHERE user_id = ?"),
                "ai": ai.engine() is not None,
            },
        )

    # --- options for select fields --------------------------------------------------------------

    def options(self, kind: str):
        s = self.need_session()
        if kind == "dataset":
            opts = search_perf.dataset_options(self.app.db, s["user_id"])
        elif kind == "client":
            opts = [
                {"value": str(r["id"]), "label": r["name"]}
                for r in self.app.db.all(
                    "SELECT id, name FROM clients WHERE user_id = ? ORDER BY name", s["user_id"]
                )
            ]
        else:
            raise ApiError(404, "No such list.")
        self.send_json(200, {"options": opts})

    # --- leads ----------------------------------------------------------------------------------

    def leads_list(self):
        s = self.need_session()
        rows = self.app.db.all(
            "SELECT * FROM leads WHERE user_id = ? ORDER BY "
            "CASE status WHEN 'new' THEN 0 WHEN 'contacted' THEN 1 "
            "WHEN 'replied' THEN 2 WHEN 'won' THEN 3 ELSE 4 END, "
            "score DESC, id DESC LIMIT 2000",
            s["user_id"],
        )
        self.send_json(
            200,
            {
                "leads": [
                    {
                        **{k: r[k] for k in r.keys() if k not in ("user_id", "problems")},
                        "problems": json.loads(r["problems"]),
                    }
                    for r in rows
                ],
                "statuses": LEAD_STATUSES,
            },
        )

    def lead_update(self):
        s = self.need_session()
        b = self.body()
        lid = b.get("id")
        if not isinstance(lid, int):
            raise ApiError(400, "Unknown lead.")
        sets, args = [], []
        if "status" in b:
            if b["status"] not in LEAD_STATUSES:
                raise ApiError(400, "Unknown status.")
            sets.append("status = ?")
            args.append(b["status"])
        if "notes" in b:
            sets.append("notes = ?")
            args.append(str(b["notes"])[:4000])
        if not sets:
            raise ApiError(400, "Nothing to change.")
        n = self.app.db.run(
            f"UPDATE leads SET {', '.join(sets)}, updated_at = ? WHERE id = ? AND user_id = ?",
            *args,
            now(),
            lid,
            s["user_id"],
        ).rowcount
        if not n:
            raise ApiError(404, "Unknown lead.")
        self.send_json(200, {"ok": True})

    def lead_delete(self):
        s = self.need_session()
        lid = self.body().get("id")
        if not isinstance(lid, int):
            raise ApiError(400, "Unknown lead.")
        self.app.db.run("DELETE FROM leads WHERE id = ? AND user_id = ?", lid, s["user_id"])
        self.send_json(200, {"ok": True})

    def lead_import(self):
        s = self.need_session()
        text = str(self.body(limit=MAX_UPLOAD).get("csv", ""))
        try:
            added, skipped = import_leads(self.app.db, s["user_id"], text)
        except InputProblem as exc:
            raise ApiError(400, str(exc)) from exc
        self.send_json(200, {"ok": True, "added": added, "skipped": skipped})

    def lead_export(self):
        s = self.need_session()
        rows = self.app.db.all("SELECT * FROM leads WHERE user_id = ? ORDER BY id", s["user_id"])
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = [
            "name",
            "category",
            "website",
            "phone",
            "email",
            "address",
            "city",
            "status",
            "score",
            "notes",
            "source",
        ]
        w.writerow(cols + ["problems"])
        for r in rows:
            w.writerow(
                [_csv_safe(r[c]) for c in cols] + [_csv_safe("; ".join(json.loads(r["problems"])))]
            )
        data = buf.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="rankloom-leads.csv"')
        self.send_header("Content-Length", str(len(data)))
        self._headers_common()
        self.end_headers()
        self.wfile.write(data)

    # --- clients and reports --------------------------------------------------------------------

    def clients_list(self):
        s = self.need_session()
        rows = self.app.db.all(
            "SELECT * FROM clients WHERE user_id = ? ORDER BY name", s["user_id"]
        )
        last = {
            r["cid"]: r
            for r in self.app.db.all(
                "SELECT CAST(json_extract(input_json, '$.client') AS INTEGER) AS cid, "
                "MAX(created_at) AS at, MAX(id) AS id FROM runs WHERE user_id = ? AND "
                "tool = 'client-reports' AND status = 'ok' GROUP BY cid",
                s["user_id"],
            )
        }
        self.send_json(
            200,
            {
                "clients": [
                    {
                        **{k: r[k] for k in r.keys() if k != "user_id"},
                        "last_report": last[r["id"]]["at"] if r["id"] in last else None,
                        "last_report_id": last[r["id"]]["id"] if r["id"] in last else None,
                    }
                    for r in rows
                ]
            },
        )

    def client_save(self):
        s = self.need_session()
        b = self.body()
        name = str(b.get("name", "")).strip()[:120]
        if not name:
            raise ApiError(400, "Enter the client's name.", field="name")
        vals = {
            k: str(b.get(k, "")).strip()[:300]
            for k in ("website", "contact", "brand", "city", "niche", "notes")
        }
        from .engines import market

        country = str(b.get("country", "")).strip().lower()
        extra = {
            "country": country if country in market.NAMES else "",
            "work_notes": str(b.get("work_notes", "")).strip()[:4000],
            "hide_fixes": str(b.get("hide_fixes", "")).strip()[:4000],
        }
        gsc = b.get("gsc_dataset")
        gsc = int(gsc) if str(gsc or "").isdigit() else None
        if gsc and not self.app.db.one(
            "SELECT 1 FROM gsc_datasets WHERE id = ? AND user_id = ?", gsc, s["user_id"]
        ):
            raise ApiError(400, "Unknown Search Console report.")
        cid = b.get("id")
        if isinstance(cid, int):
            n = self.app.db.run(
                "UPDATE clients SET name = ?, website = ?, contact = ?, brand = ?, city = ?, "
                "niche = ?, notes = ?, gsc_dataset = ?, country = ?, work_notes = ?, "
                "hide_fixes = ? WHERE id = ? AND user_id = ?",
                name,
                *vals.values(),
                gsc,
                *extra.values(),
                cid,
                s["user_id"],
            ).rowcount
            if not n:
                raise ApiError(404, "Unknown client.")
        else:
            cid = self.app.db.run(
                "INSERT INTO clients (user_id, name, website, contact, brand, city, niche, notes, "
                "gsc_dataset, created_at, country, work_notes, hide_fixes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                s["user_id"],
                name,
                *vals.values(),
                gsc,
                now(),
                *extra.values(),
            ).lastrowid
        self.send_json(200, {"ok": True, "id": cid})

    def client_delete(self):
        s = self.need_session()
        cid = self.body().get("id")
        if not isinstance(cid, int):
            raise ApiError(400, "Unknown client.")
        self.app.db.run("DELETE FROM clients WHERE id = ? AND user_id = ?", cid, s["user_id"])
        self.send_json(200, {"ok": True})

    def gsc_delete(self):
        s = self.need_session()
        did = self.body().get("id")
        if not isinstance(did, int):
            raise ApiError(400, "Unknown report.")
        self.app.db.run("DELETE FROM gsc_datasets WHERE id = ? AND user_id = ?", did, s["user_id"])
        self.app.db.run(
            "UPDATE clients SET gsc_dataset = NULL WHERE gsc_dataset = ? AND user_id = ?",
            did,
            s["user_id"],
        )
        self.send_json(200, {"ok": True})

    # --- Job Radar ------------------------------------------------------------------------------

    def query(self) -> dict:
        return {k: v[0][:200] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _jr(self, fn, *args):
        self.need_session()
        try:
            return fn(*args)
        except jobradar_link.NotConnected as exc:
            raise ApiError(409, str(exc), not_connected=True) from exc
        except sqlite3.OperationalError as exc:
            raise ApiError(503, f"job-radar's database is busy ({exc}). Try again.") from exc

    def jr_status(self):
        data = self._jr(jobradar_link.status)
        self.send_json(200, {**data, "crawl": self.app.crawler.state()})

    def jr_jobs(self):
        self.send_json(200, self._jr(jobradar_link.jobs, self.query()))

    def jr_directory(self):
        kind = self.query().get("kind", "")
        rows = self._jr(jobradar_link.directory, kind)
        extra = []
        family = {
            "fellowship": "Fellowship / programme",
            "pakistan": "Pakistan public sector (CS/IT/AI)",
            "platforms": "AI data work (contract)",
        }.get(self.query().get("with", ""))
        if family:
            extra = self._jr(jobradar_link.lens_family, family)
        self.send_json(200, {"entries": rows, "postings": extra})

    def jr_yc(self):
        self.send_json(200, self._jr(jobradar_link.yc, self.query()))

    def jr_portfolio(self):
        self.send_json(200, self._jr(jobradar_link.portfolio, self.query()))

    def jr_crawl(self):
        self.need_session()
        what = str(self.body().get("what", ""))
        try:
            self.app.crawler.start(what)
        except jobradar_link.NotConnected as exc:
            raise ApiError(409, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise ApiError(409, str(exc)) from exc
        self.send_json(200, {"ok": True, "crawl": self.app.crawler.state()})

    # --- GitHub ---------------------------------------------------------------------------------

    def _gh_token(self, s) -> str:
        row = self.app.db.one("SELECT github_token FROM users WHERE id = ?", s["user_id"])
        if row["github_token"] is None:
            raise ApiError(409, "Connect GitHub first.")
        return self.app.box.open(row["github_token"])

    def _gh_guard(self, s):
        if self.app.limited("github-user", str(s["user_id"])):
            raise ApiError(429, "Too many GitHub requests. Wait a few minutes.")

    def github_status(self):
        s = self.need_session()
        self.send_json(
            200,
            {
                "oauth": github.oauth_client() is not None,
                "connected": bool(s["github_login"]),
                "login": s["github_login"],
            },
        )

    def github_start(self):
        s = self.need_session()
        client = github.oauth_client()
        if client is None:
            raise ApiError(
                409,
                "GitHub sign-in is not set up on this server. Connect with a "
                "personal access token instead.",
            )
        state = secrets.token_urlsafe(24)
        self.app.db.run(
            "UPDATE sessions SET oauth_state = ? WHERE token_hash = ?", state, s["token_hash"]
        )
        url = github.authorize_url(client[0], state, self.app.base_url + "/auth/github/callback")
        self.send_json(200, {"url": url})

    def github_callback(self, q: dict):
        s = self.app.session(self._token())
        if s is None or s["mfa_pending"]:
            return self.redirect("/login")
        state = (q.get("state") or [""])[0]
        code = (q.get("code") or [""])[0]
        client = github.oauth_client()
        if (
            not client
            or not state
            or not s["oauth_state"]
            or not secrets.compare_digest(state, s["oauth_state"])
        ):
            return self.redirect("/settings?github=state#github")
        self.app.db.run(
            "UPDATE sessions SET oauth_state = NULL WHERE token_hash = ?", s["token_hash"]
        )
        try:
            token = github.exchange_code(
                client[0], client[1], code, self.app.base_url + "/auth/github/callback"
            )
            login = github.whoami(token)
        except github.GitHubError:
            return self.redirect("/settings?github=failed#github")
        self._store_github(s["user_id"], token, login)
        self.redirect("/settings?github=connected#github")

    def _store_github(self, uid: int, token: str, login: str):
        self.app.db.run(
            "UPDATE users SET github_token = ?, github_login = ? WHERE id = ?",
            self.app.box.seal(token),
            login,
            uid,
        )

    def github_token(self):
        s = self.need_session()
        self._gh_guard(s)
        token = str(self.body().get("token", "")).strip()
        if not re.fullmatch(
            r"(gh[pousr]_[A-Za-z0-9_]{20,255}|github_pat_[A-Za-z0-9_]{20,255})", token
        ):
            raise ApiError(400, "That does not look like a GitHub token.", field="token")
        try:
            login = github.whoami(token)
        except github.GitHubError as exc:
            raise ApiError(400, str(exc), field="token") from exc
        self._store_github(s["user_id"], token, login)
        self.send_json(200, {"ok": True, "login": login})

    def github_disconnect(self):
        s = self.need_session()
        self.app.db.run(
            "UPDATE users SET github_token = NULL, github_login = NULL WHERE id = ?", s["user_id"]
        )
        self.send_json(200, {"ok": True})

    def github_repos(self):
        s = self.need_session()
        self._gh_guard(s)
        try:
            repos = github.list_repos(self._gh_token(s))
        except github.GitHubError as exc:
            raise ApiError(502, str(exc)) from exc
        self.send_json(200, {"repos": repos})

    def github_import(self):
        s = self.need_session()
        self._gh_guard(s)
        repo = str(self.body().get("repo", "")).strip()
        try:
            info = github.import_repo(self._gh_token(s), repo)
        except github.GitHubError as exc:
            raise ApiError(400 if exc.status in (0, 404) else 502, str(exc)) from exc
        self.app.db.run(
            "INSERT INTO imports (user_id, repo, description, default_branch, languages_json, "
            "file_count, private, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, repo) DO UPDATE SET description = excluded.description, "
            "default_branch = excluded.default_branch, languages_json = excluded.languages_json,"
            " file_count = excluded.file_count, private = excluded.private, "
            "imported_at = excluded.imported_at",
            s["user_id"],
            info["repo"],
            info["description"],
            info["default_branch"],
            json.dumps(info["languages"]),
            info["file_count"],
            int(info["private"]),
            now(),
        )
        self.send_json(200, {"ok": True, "import": info})

    def imports(self):
        s = self.need_session()
        rows = self.app.db.all(
            "SELECT * FROM imports WHERE user_id = ? ORDER BY imported_at DESC", s["user_id"]
        )
        self.send_json(
            200,
            {
                "imports": [
                    {
                        "id": r["id"],
                        "repo": r["repo"],
                        "description": r["description"],
                        "default_branch": r["default_branch"],
                        "languages": json.loads(r["languages_json"]),
                        "file_count": r["file_count"],
                        "private": bool(r["private"]),
                        "imported_at": r["imported_at"],
                    }
                    for r in rows
                ]
            },
        )

    def import_delete(self):
        s = self.need_session()
        rid = self.body().get("id")
        if not isinstance(rid, int):
            raise ApiError(400, "Unknown import.")
        self.app.db.run("DELETE FROM imports WHERE id = ? AND user_id = ?", rid, s["user_id"])
        self.send_json(200, {"ok": True})


ROUTES = {
    ("GET", "/api/me"): Handler.me,
    ("POST", "/api/auth/register"): Handler.register,
    ("POST", "/api/auth/login"): Handler.login,
    ("POST", "/api/auth/2fa"): Handler.two_factor_login,
    ("POST", "/api/auth/logout"): Handler.logout,
    ("POST", "/api/auth/forgot"): Handler.forgot,
    ("POST", "/api/auth/reset"): Handler.reset,
    ("POST", "/api/account/password"): Handler.change_password,
    ("POST", "/api/account/profile"): Handler.profile,
    ("GET", "/api/account/sessions"): Handler.sessions,
    ("POST", "/api/account/sessions/revoke"): Handler.revoke_session,
    ("GET", "/api/2fa"): Handler.tfa_status,
    ("POST", "/api/2fa/setup"): Handler.tfa_setup,
    ("POST", "/api/2fa/enable"): Handler.tfa_enable,
    ("POST", "/api/2fa/disable"): Handler.tfa_disable,
    ("POST", "/api/2fa/recovery"): Handler.tfa_recovery,
    ("GET", "/api/tools"): Handler.tools,
    ("POST", "/api/events"): Handler.event,
    ("GET", "/api/dashboard"): Handler.dashboard,
    ("GET", "/api/github"): Handler.github_status,
    ("POST", "/api/github/start"): Handler.github_start,
    ("POST", "/api/github/token"): Handler.github_token,
    ("POST", "/api/github/disconnect"): Handler.github_disconnect,
    ("GET", "/api/github/repos"): Handler.github_repos,
    ("POST", "/api/github/import"): Handler.github_import,
    ("GET", "/api/imports"): Handler.imports,
    ("GET", "/api/leads"): Handler.leads_list,
    ("POST", "/api/leads/update"): Handler.lead_update,
    ("POST", "/api/leads/delete"): Handler.lead_delete,
    ("POST", "/api/leads/import"): Handler.lead_import,
    ("GET", "/api/leads/export"): Handler.lead_export,
    ("GET", "/api/clients"): Handler.clients_list,
    ("POST", "/api/clients/save"): Handler.client_save,
    ("POST", "/api/clients/delete"): Handler.client_delete,
    ("POST", "/api/gsc/delete"): Handler.gsc_delete,
    ("GET", "/api/jobradar/status"): Handler.jr_status,
    ("GET", "/api/jobradar/jobs"): Handler.jr_jobs,
    ("GET", "/api/jobradar/directory"): Handler.jr_directory,
    ("GET", "/api/jobradar/yc"): Handler.jr_yc,
    ("GET", "/api/jobradar/portfolio"): Handler.jr_portfolio,
    ("POST", "/api/jobradar/crawl"): Handler.jr_crawl,
    ("POST", "/api/imports/delete"): Handler.import_delete,
}

PATTERN_ROUTES = [
    (("POST", re.compile(r"/api/tools/([a-z0-9-]+)/([a-z0-9-]+)/run")), Handler.run_tool),
    (("GET", re.compile(r"/api/options/([a-z]+)")), Handler.options),
    (("GET", re.compile(r"/api/tools/([a-z0-9-]+)/runs")), Handler.tool_runs),
    (("GET", re.compile(r"/api/tools/([a-z0-9-]+)/stats")), Handler.tool_stats),
    (("GET", re.compile(r"/api/runs/(\d{1,12})")), Handler.run_detail),
]


def make_server(app: App, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run the Rankloom web app.")
    p.add_argument("--host", default=os.environ.get("RANKLOOM_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("RANKLOOM_PORT", "8130")))
    p.add_argument("--data", default=os.environ.get("RANKLOOM_DATA", str(ROOT / "data")))
    p.add_argument("--no-browser", action="store_true", help="accepted for launchers; ignored")
    args = p.parse_args(argv)
    base = os.environ.get("RANKLOOM_BASE_URL", f"http://{args.host}:{args.port}")
    app = App(args.data, base, secure_cookies=base.startswith("https://"))
    server = make_server(app, args.host, args.port)
    print(f"Rankloom on {base}  (data in {args.data})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
