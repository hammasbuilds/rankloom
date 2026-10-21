"""The real server on a real socket, driven the way the browser drives it."""

import http.client
import json
import re
import threading

import pytest

from rankloom import engines, github, security, server

GOOD_PW = "tall-orange-river-42"


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None

    def call(self, method, path, body=None, headers=None, csrf=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if csrf:
            h["X-Rankloom"] = "1"
        if self.cookie:
            h["Cookie"] = f"{server.COOKIE}={self.cookie}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        raw = resp.read()
        for k, v in resp.getheaders():
            if k.lower() == "set-cookie" and v.startswith(server.COOKIE + "="):
                value = v.split(";")[0].split("=", 1)[1]
                self.cookie = value or None
        conn.close()
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = raw.decode(errors="replace")
        return resp.status, payload, dict(resp.getheaders())

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RANKLOOM_QUIET", "1")
    monkeypatch.delenv("RANKLOOM_SMTP_HOST", raising=False)
    monkeypatch.delenv("RANKLOOM_GITHUB_CLIENT_ID", raising=False)
    a = server.App(tmp_path, "https://rankloom.test")
    srv = server.make_server(a, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    a.port = srv.server_address[1]
    yield a
    srv.shutdown()
    srv.server_close()


def new_client(app):
    return Client(app.port)


def register(app, email="ayesha@example.com", name="Ayesha Khan"):
    c = new_client(app)
    st, body, _ = c.post("/api/auth/register", {"name": name, "email": email, "password": GOOD_PW})
    assert st == 201, body
    return c


# --- accounts ------------------------------------------------------------------------------


def test_register_signs_in_and_me_reports_the_user(app):
    c = register(app)
    st, body, _ = c.get("/api/me")
    assert st == 200
    assert body["user"]["email"] == "ayesha@example.com"
    assert body["user"]["two_factor"] is False


def test_session_cookie_is_httponly_and_lax_and_only_its_hash_is_stored(app):
    c = new_client(app)
    _, _, headers = c.post(
        "/api/auth/register", {"name": "A", "email": "a@example.com", "password": GOOD_PW}
    )
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    stored = [r["token_hash"] for r in app.db.all("SELECT token_hash FROM sessions")]
    assert c.cookie not in stored
    assert security.token_hash(c.cookie) in stored


def test_duplicate_email_and_weak_password_are_refused_with_the_field(app):
    register(app)
    c = new_client(app)
    st, body, _ = c.post(
        "/api/auth/register", {"name": "B", "email": "AYESHA@example.com", "password": GOOD_PW}
    )
    assert st == 409 and body["field"] == "email"
    st, body, _ = c.post(
        "/api/auth/register", {"name": "B", "email": "b@example.com", "password": "short"}
    )
    assert st == 400 and body["field"] == "password"


def test_login_with_a_wrong_password_and_an_unknown_email_read_the_same(app):
    register(app)
    c = new_client(app)
    st1, b1, _ = c.post(
        "/api/auth/login", {"email": "ayesha@example.com", "password": "nope-nope-nope"}
    )
    st2, b2, _ = c.post(
        "/api/auth/login", {"email": "nobody@example.com", "password": "nope-nope-nope"}
    )
    assert st1 == st2 == 401
    assert b1["error"] == b2["error"]


def test_state_changes_need_the_custom_header_and_a_matching_origin(app):
    c = register(app)
    st, _, _ = c.post("/api/account/profile", {"name": "X"}, csrf=False)
    assert st == 403
    st, _, _ = c.post(
        "/api/account/profile", {"name": "X"}, headers={"Origin": "https://evil.example"}
    )
    assert st == 403
    st, _, _ = c.post(
        "/api/account/profile",
        {"name": "Ayesha K"},
        headers={"Origin": f"http://127.0.0.1:{app.port}"},
    )
    assert st == 200


def test_login_is_rate_limited_per_account(app):
    register(app)
    c = new_client(app)
    codes = [
        c.post("/api/auth/login", {"email": "ayesha@example.com", "password": "wrong-wrong-1"})[0]
        for _ in range(9)
    ]
    assert codes[:8] == [401] * 8
    assert codes[8] == 429


def test_logout_ends_the_session(app):
    c = register(app)
    token = c.cookie
    c.post("/api/auth/logout")
    other = new_client(app)
    other.cookie = token
    assert other.get("/api/me")[0] == 401


def test_change_password_ends_other_sessions_but_keeps_this_one(app):
    a = register(app)
    b = new_client(app)
    assert b.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})[0] == 200
    st, body, _ = a.post(
        "/api/account/password", {"current": GOOD_PW, "new": "new-green-forest-77"}
    )
    assert st == 200 and body["other_sessions_ended"] == 1
    assert a.get("/api/me")[0] == 200
    assert b.get("/api/me")[0] == 401
    st, body, _ = a.post("/api/account/password", {"current": "wrong", "new": "x" * 12})
    assert st == 400 and body["field"] == "current"


def test_sessions_list_and_revoke_one(app):
    a = register(app)
    b = new_client(app)
    b.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
    _, body, _ = a.get("/api/account/sessions")
    assert len(body["sessions"]) == 2
    other = next(s for s in body["sessions"] if not s["current"])
    a.post("/api/account/sessions/revoke", {"id": other["id"]})
    assert b.get("/api/me")[0] == 401
    assert a.get("/api/me")[0] == 200


# --- password reset ------------------------------------------------------------------------


def reset_link(app):
    body = app.db.one("SELECT body FROM outbox ORDER BY id DESC LIMIT 1")["body"]
    return re.search(r"https://rankloom\.test/reset\?token=(\S+)", body).group(1)


def test_reset_flow_uses_the_configured_base_url_and_works_once(app):
    a = register(app)
    c = new_client(app)
    st, body, _ = c.post(
        "/api/auth/forgot", {"email": "ayesha@example.com"}, headers={"Host": "attacker.example"}
    )
    assert st == 200 and body["delivery"] == "outbox"
    token = reset_link(app)  # built from the configured URL, not the forged Host
    st, _, _ = c.post("/api/auth/reset", {"token": token, "password": "brand-new-lake-31"})
    assert st == 200
    assert a.get("/api/me")[0] == 401  # every session ended
    st, _, _ = c.post("/api/auth/reset", {"token": token, "password": "another-new-one-9"})
    assert st == 400
    assert (
        c.post("/api/auth/login", {"email": "ayesha@example.com", "password": "brand-new-lake-31"})[
            0
        ]
        == 200
    )


def test_with_smtp_the_outbox_log_holds_no_working_reset_link(app, monkeypatch):
    from rankloom import mail

    sent = []

    class FakeSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **kw):
            pass

        def send_message(self, msg):
            sent.append(msg.get_content())

    monkeypatch.setenv("RANKLOOM_SMTP_HOST", "smtp.test")
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    register(app)
    st, body, _ = new_client(app).post("/api/auth/forgot", {"email": "ayesha@example.com"})
    assert st == 200 and body["delivery"] == "smtp"
    assert re.search(r"reset\?token=[A-Za-z0-9_-]{20,}", sent[0])  # the email has the link
    logged = app.db.one("SELECT body FROM outbox ORDER BY id DESC LIMIT 1")["body"]
    assert "reset?token=[sent by email]" in logged and not re.search(r"token=[A-Za-z0-9_-]{20}", logged)


def test_forgot_answers_the_same_for_unknown_emails(app):
    c = new_client(app)
    st, body, _ = c.post("/api/auth/forgot", {"email": "ghost@example.com"})
    assert st == 200 and body["ok"]
    assert app.db.one("SELECT COUNT(*) FROM outbox")[0] == 0


# --- 2-step verification -------------------------------------------------------------------


def enable_two_step(c):
    _, setup, _ = c.post("/api/2fa/setup")
    code = security.hotp(setup["secret"], security.totp_step())
    st, body, _ = c.post("/api/2fa/enable", {"code": code})
    assert st == 200, body
    return setup["secret"], body["recovery_codes"]


def test_two_step_setup_then_login_needs_a_code(app):
    c = register(app)
    secret, codes = enable_two_step(c)
    assert len(codes) == 10
    assert c.get("/api/me")[1]["user"]["two_factor"] is True

    d = new_client(app)
    st, body, _ = d.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
    assert st == 200 and body["mfa_required"] is True
    assert d.get("/api/me")[1] == {"user": None, "mfa_required": True}
    assert d.get("/api/tools")[0] == 401  # a half-signed-in session reaches nothing
    pending = d.cookie
    st, _, _ = d.post("/api/auth/2fa", {"code": security.hotp(secret, security.totp_step() + 1)})
    assert st == 200
    assert d.cookie != pending  # promoted by a new token, not by flipping a flag
    assert d.get("/api/tools")[0] == 200


def test_a_code_used_once_cannot_sign_in_again(app):
    c = register(app)
    secret, _ = enable_two_step(c)
    code = security.hotp(secret, security.totp_step() + 1)
    d = new_client(app)
    d.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
    assert d.post("/api/auth/2fa", {"code": code})[0] == 200
    e = new_client(app)
    e.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
    assert e.post("/api/auth/2fa", {"code": code})[0] == 401


def test_a_recovery_code_works_exactly_once(app):
    c = register(app)
    _, codes = enable_two_step(c)
    for expected in (200, 401):
        d = new_client(app)
        d.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
        assert d.post("/api/auth/2fa", {"code": codes[0].upper()})[0] == expected
    st, body, _ = c.get("/api/2fa")
    assert body["recovery_left"] == 9


def test_two_step_codes_are_rate_limited(app):
    c = register(app)
    enable_two_step(c)
    d = new_client(app)
    d.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})
    statuses = [d.post("/api/auth/2fa", {"code": "000000"})[0] for _ in range(7)]
    assert statuses[-1] == 429


def test_turning_two_step_off_needs_password_and_code(app):
    c = register(app)
    secret, _ = enable_two_step(c)
    code = security.hotp(secret, security.totp_step() + 1)
    assert c.post("/api/2fa/disable", {"password": "wrong", "code": code})[0] == 400
    assert c.post("/api/2fa/disable", {"password": GOOD_PW, "code": code})[0] == 200
    assert c.get("/api/2fa")[1]["enabled"] is False


def test_new_recovery_codes_need_a_fresh_code_not_just_the_password(app):
    c = register(app)
    secret, old = enable_two_step(c)
    for code in ("000000", "", None):
        body = {"password": GOOD_PW} if code is None else {"password": GOOD_PW, "code": code}
        st, reply, _ = c.post("/api/2fa/recovery", body)
        assert st == 400 and reply["field"] == "code"
    code = security.hotp(secret, security.totp_step() + 1)
    st, reply, _ = c.post("/api/2fa/recovery", {"password": GOOD_PW, "code": code})
    assert st == 200 and len(reply["recovery_codes"]) == 10 and reply["recovery_codes"] != old
    # The code that made them is spent.
    assert c.post("/api/2fa/recovery", {"password": GOOD_PW, "code": code})[0] == 400


def test_password_rechecks_are_rate_limited_per_user(app):
    c = register(app)
    statuses = [
        c.post("/api/account/password", {"current": "wrong", "new": "new-green-forest-77"})[0]
        for _ in range(7)
    ]
    assert statuses[:6] == [400] * 6 and statuses[6] == 429


def test_correct_sign_ins_do_not_use_up_the_address_limit(app):
    register(app)
    for _ in range(25):  # more than the 20 per address an office would share
        d = new_client(app)
        assert d.post("/api/auth/login", {"email": "ayesha@example.com", "password": GOOD_PW})[
            0
        ] == 200


def test_the_totp_secret_is_sealed_in_the_database(app):
    c = register(app)
    secret, _ = enable_two_step(c)
    blob = app.db.one("SELECT totp_secret FROM users")["totp_secret"]
    assert secret.encode() not in blob
    assert app.box.open(blob) == secret


# --- tools, runs, analytics ----------------------------------------------------------------


def test_catalog_has_six_tools_each_with_sub_tools_and_an_about(app):
    c = register(app)
    _, body, _ = c.get("/api/tools")
    tools = body["tools"]
    assert [t["name"] for t in tools] == [
        "Site Audit",
        "AI Visibility",
        "Lead Finder",
        "Search Performance",
        "Content Studio",
        "Client Reports",
        "Job Radar",
    ]
    runnable = set()
    for t in tools:
        assert t["about"] and len(t["subtools"]) >= 2
        for sub in t["subtools"]:
            assert sub["about"] and sub["does"] and sub["input"] and sub["output"], sub["slug"]
            if sub["kind"] == "run":
                runnable.add(f"{t['slug']}/{sub['slug']}")
                assert sub["fields"], sub["slug"]
    assert runnable == set(engines.ENGINES)  # every run form has an engine, and no engine hides


def test_a_sub_tool_needing_ai_says_how_to_set_it_up_and_records_no_run(app, monkeypatch):
    monkeypatch.delenv("RANKLOOM_AI", raising=False)
    c = register(app)
    _, body, _ = c.get("/api/tools")
    answers = next(s for t in body["tools"] for s in t["subtools"] if s["slug"] == "answers")
    assert answers["status"] == "needs-ai"
    st, body, _ = c.post(
        "/api/tools/ai-visibility/answers/run", {"fields": {"brand": "X", "niche": "dentist"}}
    )
    assert st == 409 and body["needs_ai"] and "RANKLOOM_AI" in body["error"]
    assert app.db.one("SELECT COUNT(*) FROM runs")[0] == 0


def test_required_fields_are_checked_before_the_engine_runs(app, monkeypatch):
    called = []
    monkeypatch.setitem(server.ENGINES, "site-audit/page", lambda f, ctx: called.append(f))
    c = register(app)
    st, body, _ = c.post("/api/tools/site-audit/page/run", {"fields": {"url": ""}})
    assert st == 400 and "Page address" in body["error"]
    assert called == []


def test_runs_feed_the_tool_dashboard_and_the_overview(app, monkeypatch):
    calls = []

    def fake(fields, ctx):
        calls.append(fields)
        return f"{fields['url']} scored 70/100", 70, {"score": 70}

    monkeypatch.setitem(server.ENGINES, "site-audit/page", fake)
    c = register(app)
    c.post("/api/events", {"tool": "site-audit", "subtool": "page", "kind": "open"})
    c.post("/api/events", {"tool": "site-audit", "subtool": "page", "kind": "open"})  # one visit
    for _ in range(2):
        st, body, _ = c.post(
            "/api/tools/site-audit/page/run", {"fields": {"url": "example.com", "evil": "dropped"}}
        )
        assert st == 200 and body["score"] == 70
    assert calls[0] == {"url": "example.com"}  # unknown fields never reach the engine
    _, stats, _ = c.get("/api/tools/site-audit/stats")
    assert stats["opens"] == 1 and stats["runs"] == 2 and stats["ok"] == 2
    page = next(x for x in stats["subtools"] if x["slug"] == "page")
    assert page["runs"] == 2 and page["avg_score"] == 70
    assert {x["slug"] for x in stats["subtools"]} == {"page", "crawl", "local"}
    assert len(stats["daily"]) == 14 and stats["daily"][-1]["runs"] == 2
    _, dash, _ = c.get("/api/dashboard")
    row = next(t for t in dash["tools"] if t["slug"] == "site-audit")
    assert row["runs"] == 2 and row["opens"] == 1
    assert dash["recent"][0]["subtool"] == "page"


def test_a_refused_address_is_a_recorded_failed_run_not_a_crash(app):
    c = register(app)
    st, body, _ = c.post("/api/tools/site-audit/page/run", {"fields": {"url": "http://127.0.0.1/"}})
    assert st == 422 and body["status"] == "error"
    _, stats, _ = c.get("/api/tools/site-audit/stats")
    assert stats["errors"] == 1


def test_one_user_cannot_read_another_users_run(app, monkeypatch):
    monkeypatch.setitem(server.ENGINES, "site-audit/page", lambda f, ctx: ("ok", 50, {}))
    a = register(app)
    _, run, _ = a.post("/api/tools/site-audit/page/run", {"fields": {"url": "example.com"}})
    b = register(app, email="bilal@example.com", name="Bilal")
    assert b.get(f"/api/runs/{run['id']}")[0] == 404
    assert a.get(f"/api/runs/{run['id']}")[0] == 200


def test_the_real_page_audit_runs_through_the_app_fetcher(app):
    from test_site_audit import GOOD, fetcher

    app.fetch = fetcher({"https://solar.example/": (200, GOOD, {}, "https://solar.example/", [])})
    c = register(app)
    st, body, _ = c.post("/api/tools/site-audit/page/run", {"fields": {"url": "solar.example"}})
    assert st == 200
    view = body["output"]["view"]
    assert view["headline"]["score"] == body["score"]
    assert [b["type"] for b in view["blocks"]] == ["facts", "checks"]


# --- leads ---------------------------------------------------------------------------------


def test_lead_csv_import_update_export_and_isolation(app):
    c = register(app)
    csv_text = (
        "Business Name,Website,Phone,City\n"
        "Smile Care,smilecare.example,0300-1234567,Lahore\n"
        '=HYPERLINK("http://evil"),,,Karachi\n'
        ",nobody.example,,\n"
    )
    st, body, _ = c.post("/api/leads/import", {"csv": csv_text})
    assert st == 200 and body["added"] == 2 and body["skipped"] == 1
    _, leads, _ = c.get("/api/leads")
    names = {x["name"]: x for x in leads["leads"]}
    assert names["Smile Care"]["phone"] == "0300-1234567"
    assert names['=HYPERLINK("http://evil")']["problems"] == ["no website listed"]
    lid = names["Smile Care"]["id"]
    assert (
        c.post("/api/leads/update", {"id": lid, "status": "contacted", "notes": "called"})[0] == 200
    )
    assert c.post("/api/leads/update", {"id": lid, "status": "hacked"})[0] == 400
    st, raw, headers = c.get("/api/leads/export")
    assert st == 200 and headers["Content-Type"].startswith("text/csv")
    assert "'=HYPERLINK" in raw  # a formula cell is defused for Excel
    assert "contacted" in raw and "called" in raw
    other = register(app, email="bilal@example.com", name="Bilal")
    assert other.get("/api/leads")[1]["leads"] == []
    assert other.post("/api/leads/update", {"id": lid, "status": "won"})[0] == 404


def test_an_exported_lead_list_imports_back_unchanged(app):
    c = register(app)
    c.post("/api/leads/import", {"csv": "name,website,phone,city\nAvalon,avalon.example,+44 161 224 4345,Manchester\n"})
    lid = c.get("/api/leads")[1]["leads"][0]["id"]
    c.post("/api/leads/update", {"id": lid, "status": "replied", "notes": "call Tuesday"})
    app.db.run("UPDATE leads SET score = 63, problems = ? WHERE id = ?", '["no H1", "slow"]', lid)
    _, raw, _ = c.get("/api/leads/export")
    assert "'+44 161 224 4345" in raw  # defused for Excel on the way out
    other = register(app, email="bilal@example.com", name="Bilal")
    assert other.post("/api/leads/import", {"csv": raw.lstrip("﻿")})[0] == 200
    back = other.get("/api/leads")[1]["leads"][0]
    assert back["phone"] == "+44 161 224 4345"
    assert back["score"] == 63 and back["problems"] == ["no H1", "slow"]
    assert back["status"] == "replied" and back["notes"] == "call Tuesday"


def test_an_imported_lead_without_a_website_ranks_like_a_searched_one(app):
    from rankloom.engines.leads import opportunity

    c = register(app)
    c.post("/api/leads/import", {"csv": "name,city\nNo Site Bakery,Lahore\n"})
    assert c.get("/api/leads")[1]["leads"][0]["score"] == opportunity({})


def test_business_search_saves_ranked_leads(app, monkeypatch):
    from test_site_audit import BAD, fetcher

    from rankloom import sources

    monkeypatch.setattr(
        sources,
        "places",
        lambda trade, city, limit=50, country="": [
            {
                "name": "No Site Dental",
                "category": "dentist",
                "website": "",
                "phone": "0300",
                "email": "",
                "address": "",
                "city": city,
                "source": "osm",
            },
            {
                "name": "Weak Site Dental",
                "category": "dentist",
                "website": "bad.example",
                "phone": "",
                "email": "",
                "address": "",
                "city": city,
                "source": "osm",
            },
        ],
    )
    app.fetch = fetcher({"https://bad.example/": (200, BAD, {}, "https://bad.example/", [])})
    c = register(app)
    st, body, _ = c.post(
        "/api/tools/lead-finder/search/run", {"fields": {"trade": "dentists", "city": "Lahore"}}
    )
    assert st == 200, body
    out = body["output"]
    assert out["found"] == 2 and out["with_site"] == 1 and out["audited"] == 1
    # A weak site we checked outranks a business merely listed without one.
    assert [x["name"] for x in out["leads"]] == ["Weak Site Dental", "No Site Dental"]
    assert out["leads"][1]["problems"] == [
        "website not listed in the directory (check before contacting)"
    ]
    _, leads, _ = c.get("/api/leads")
    assert len(leads["leads"]) == 2
    weak = next(x for x in leads["leads"] if x["website"])
    assert any("not secure" in p or "phones" in p for p in weak["problems"])
    st, body, _ = c.post(
        "/api/tools/lead-finder/outreach/run", {"fields": {"lead": str(weak["id"])}}
    )
    assert st == 200
    email = body["output"]["drafts"][0]["text"]
    assert "Weak Site Dental" in email and "bad.example" in email


# --- clients, Search Console, reports ------------------------------------------------------


def gsc_zip(compare=True):
    import base64
    import io
    import zipfile

    if compare:
        q = (
            "Top queries,Last 28 days Clicks,Previous 28 days Clicks,Last 28 days Impressions,"
            "Previous 28 days Impressions,Last 28 days CTR,Previous 28 days CTR,"
            "Last 28 days Position,Previous 28 days Position\n"
            "dentist lahore,40,60,2000,2100,2%,2.86%,4.1,3.2\n"
            "teeth whitening price,2,1,900,800,0.22%,0.13%,12.5,15\n"
            "root canal cost,0,3,700,650,0%,0.46%,9.8,8.9\n"
        )
        pg = (
            "Top pages,Last 28 days Clicks,Previous 28 days Clicks,Last 28 days Impressions,"
            "Previous 28 days Impressions,Last 28 days CTR,Previous 28 days CTR,"
            "Last 28 days Position,Previous 28 days Position\n"
            "https://smile.example/,30,50,2500,2600,1.2%,1.92%,5,4\n"
            "https://smile.example/whitening,12,14,1100,950,1.09%,1.47%,11,13\n"
        )
    else:
        q = "Top queries,Clicks,Impressions,CTR,Position\ndentist lahore,40,2000,2%,4.1\n"
        pg = "Top pages,Clicks,Impressions,CTR,Position\nhttps://smile.example/,30,2500,1.2%,5\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Queries.csv", "﻿" + q)
        z.writestr("Pages.csv", pg)
        z.writestr("Countries.csv", "Country,Clicks\nPakistan,40\n")
    return [{"name": "export.zip", "data": base64.b64encode(buf.getvalue()).decode()}]


def test_search_console_import_opportunities_and_changes(app):
    c = register(app)
    st, body, _ = c.post(
        "/api/tools/search-performance/import/run",
        {"fields": {"site": "smile.example", "files": gsc_zip()}},
    )
    assert st == 200, body
    assert body["output"]["queries"] == 3 and body["output"]["pages"] == 2
    did = body["output"]["dataset"]
    _, opts, _ = c.get("/api/options/dataset")
    assert opts["options"][0]["value"] == str(did)
    st, body, _ = c.post(
        "/api/tools/search-performance/opportunities/run", {"fields": {"dataset": str(did)}}
    )
    assert st == 200
    striking = [r["key"] for r in body["output"]["striking"]]
    assert "teeth whitening price" in striking and "dentist lahore" not in striking
    low = [r["key"] for r in body["output"]["low_ctr"]]
    assert "dentist lahore" in low  # 2% at position 4, where about 8% is typical
    st, body, _ = c.post(
        "/api/tools/search-performance/changes/run", {"fields": {"dataset": str(did)}}
    )
    assert st == 200
    losers = [r["key"] for r in body["output"]["queries"]["losers"]]
    assert losers[0] == "dentist lahore"  # 60 -> 40, the biggest drop
    assert body["output"]["pages"]["now"]["clicks"] == 42


def test_changes_needs_a_comparison_export(app):
    c = register(app)
    _, body, _ = c.post(
        "/api/tools/search-performance/import/run",
        {"fields": {"site": "s", "files": gsc_zip(compare=False)}},
    )
    did = body["output"]["dataset"]
    st, body, _ = c.post(
        "/api/tools/search-performance/changes/run", {"fields": {"dataset": str(did)}}
    )
    assert st == 422 and "Compare" in body["error"]


def test_a_file_that_is_not_an_export_is_refused_with_how_to(app):
    import base64

    c = register(app)
    files = [{"name": "x.csv", "data": base64.b64encode(b"a,b\n1,2\n").decode()}]
    st, body, _ = c.post(
        "/api/tools/search-performance/import/run", {"fields": {"site": "s", "files": files}}
    )
    assert st == 422 and "Download CSV" in body["error"]


def test_clients_and_a_monthly_report(app):
    from test_site_audit import GOOD, fetcher

    app.fetch = fetcher({"https://solar.example/": (200, GOOD, {}, "https://solar.example/", [])})
    c = register(app)
    _, imp, _ = c.post(
        "/api/tools/search-performance/import/run",
        {"fields": {"site": "solar.example", "files": gsc_zip()}},
    )
    st, body, _ = c.post(
        "/api/clients/save",
        {
            "name": "Sun Power",
            "website": "solar.example",
            "city": "Lahore",
            "brand": "Ayesha Digital",
            "gsc_dataset": imp["output"]["dataset"],
        },
    )
    assert st == 200
    cid = body["id"]
    _, audit_run, _ = c.post("/api/tools/site-audit/page/run", {"fields": {"url": "solar.example"}})
    _, opts, _ = c.get("/api/options/client")
    assert opts["options"] == [{"value": str(cid), "label": "Sun Power"}]
    st, body, _ = c.post("/api/tools/client-reports/report/run", {"fields": {"client": str(cid)}})
    assert st == 200, body
    out = body["output"]
    assert out["audit"]["score"] == audit_run["score"]  # same page, same checks, same score
    assert out["gsc"]["now"]["clicks"] == 42
    assert any("solar.example" in w for w in out["work"])
    titles = [b["title"] for b in out["view"]["blocks"]]
    assert "Google search results" in titles and "Work done this month" in titles
    _, cl, _ = c.get("/api/clients")
    assert cl["clients"][0]["last_report_id"] == body["id"]
    other = register(app, email="bilal@example.com", name="Bilal")
    st, _, _ = other.post("/api/tools/client-reports/report/run", {"fields": {"client": str(cid)}})
    assert st == 422


def test_a_report_keeps_the_agencys_notes_market_and_chosen_omissions(app):
    from test_site_audit import BAD, fetcher

    app.fetch = fetcher({"https://bad.example/": (200, BAD, {}, "https://bad.example/", [])})
    c = register(app)
    st, body, _ = c.post("/api/clients/save", {"name": "Bad Co", "website": "bad.example",
                                                "country": "us", "work_notes": "- Fixed the title\nSent the GBP checklist"})
    cid = body["id"]
    st, body, _ = c.post("/api/tools/client-reports/report/run", {"fields": {"client": str(cid)}})
    out = body["output"]
    fix_rows = next(b for b in out["view"]["blocks"] if b.get("title") == "What to fix next")["rows"]
    first = fix_rows[0][1]
    assert out["work"][:2] == ["Fixed the title", "Sent the GBP checklist"]  # their words first
    assert not any("WhatsApp" in r[1] or "wa.me" in r[2] for r in fix_rows)  # a US client
    c.post("/api/clients/save", {"id": cid, "name": "Bad Co", "website": "bad.example",
                                 "country": "us", "hide_fixes": first})
    st, body, _ = c.post("/api/tools/client-reports/report/run", {"fields": {"client": str(cid)}})
    rows = next(b for b in body["output"]["view"]["blocks"] if b.get("title") == "What to fix next")["rows"]
    assert first not in [r[1] for r in rows]
    assert body["output"]["left_out"] == [first] and "left out by choice" in body["summary"]
    assert c.post("/api/clients/save", {"name": "X", "country": "zz"})[0] == 200  # unknown -> ""
    assert app.db.one("SELECT country FROM clients WHERE name = 'X'")["country"] == ""


def test_a_client_cannot_point_at_someone_elses_report(app):
    a = register(app)
    _, imp, _ = a.post(
        "/api/tools/search-performance/import/run", {"fields": {"site": "s", "files": gsc_zip()}}
    )
    b = register(app, email="bilal@example.com", name="Bilal")
    st, _, _ = b.post("/api/clients/save", {"name": "X", "gsc_dataset": imp["output"]["dataset"]})
    assert st == 400


def test_an_oversized_request_gets_413_not_a_reset(app):
    c = register(app)
    big = "x" * (server.MAX_BODY + 10)
    st, body, _ = c.post("/api/account/profile", {"name": big})
    assert st == 413


# --- GitHub --------------------------------------------------------------------------------


@pytest.fixture
def fake_github(monkeypatch):
    seen = []

    def request(method, url, headers, body=None):
        seen.append((method, url, headers.get("Authorization")))
        if url.endswith("/user"):
            return 200, b'{"login": "hammasbuilds"}'
        if "/user/repos" in url:
            return 200, json.dumps(
                [
                    {
                        "full_name": "hammasbuilds/rankloom",
                        "private": True,
                        "description": "growth tools",
                        "language": "Python",
                        "stargazers_count": 3,
                    }
                ]
            ).encode()
        if url.endswith("/repos/hammasbuilds/rankloom"):
            return (
                200,
                b'{"full_name": "hammasbuilds/rankloom", "default_branch": "main", "private": true}',
            )
        if url.endswith("/languages"):
            return 200, b'{"Python": 9000, "JavaScript": 4000}'
        if "/git/trees/" in url:
            return 200, b'{"tree": [{"type": "blob"}, {"type": "blob"}, {"type": "tree"}]}'
        return 404, b'{"message": "Not Found"}'

    monkeypatch.setattr(github, "request", request)
    return seen


TOKEN = "ghp_" + "a" * 36


def test_connect_with_a_token_list_and_import(app, fake_github):
    c = register(app)
    st, body, _ = c.post("/api/github/token", {"token": TOKEN})
    assert st == 200 and body["login"] == "hammasbuilds"
    blob = app.db.one("SELECT github_token FROM users")["github_token"]
    assert TOKEN.encode() not in blob
    assert c.get("/api/github")[1] == {"oauth": False, "connected": True, "login": "hammasbuilds"}
    _, repos, _ = c.get("/api/github/repos")
    assert repos["repos"][0]["full_name"] == "hammasbuilds/rankloom"
    st, body, _ = c.post("/api/github/import", {"repo": "hammasbuilds/rankloom"})
    assert st == 200 and body["import"]["file_count"] == 2
    _, imports, _ = c.get("/api/imports")
    assert imports["imports"][0]["languages"] == {"Python": 9000, "JavaScript": 4000}
    assert all(auth == f"Bearer {TOKEN}" for _, _, auth in fake_github if auth)


def test_github_token_never_reaches_the_browser(app, fake_github):
    c = register(app)
    c.post("/api/github/token", {"token": TOKEN})
    for path in ("/api/me", "/api/github", "/api/github/repos", "/api/imports"):
        assert TOKEN not in json.dumps(c.get(path)[1])


def test_repo_names_are_validated_before_any_request(app, fake_github):
    c = register(app)
    c.post("/api/github/token", {"token": TOKEN})
    before = len(fake_github)
    for bad in ("../../user", "a/b/c", "owner/", "x y/z"):
        assert c.post("/api/github/import", {"repo": bad})[0] == 400
    assert len(fake_github) == before


def test_oauth_start_is_refused_without_an_app_and_state_is_checked(app, monkeypatch):
    c = register(app)
    assert c.post("/api/github/start")[0] == 409
    monkeypatch.setenv("RANKLOOM_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("RANKLOOM_GITHUB_CLIENT_SECRET", "csecret")
    st, body, _ = c.post("/api/github/start")
    assert st == 200
    assert "redirect_uri=https%3A%2F%2Frankloom.test%2Fauth%2Fgithub%2Fcallback" in body["url"]
    st, _, headers = c.get("/auth/github/callback?code=x&state=forged")
    assert st == 303 and "github=state" in headers["Location"]


# --- pages ---------------------------------------------------------------------------------


def test_pages_ship_a_strict_csp_and_deep_links_get_the_app(app):
    c = new_client(app)
    for path in ("/", "/login", "/t/site-audit", "/settings"):
        st, body, headers = c.get(path, csrf=False)
        assert st == 200 and '<div id="app"' in body
        assert "script-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Frame-Options"] == "DENY"


def test_static_paths_cannot_climb_out_of_the_static_folder(app):
    c = new_client(app)
    st, body, _ = c.get("/static/../rankloom/db.py", csrf=False)
    assert "CREATE TABLE" not in body
    st, body, _ = c.get("/static/..%2frankloom%2fdb.py", csrf=False)
    assert "CREATE TABLE" not in body


def test_every_html_page_script_and_style_exists(app):
    c = new_client(app)
    _, html, _ = c.get("/", csrf=False)
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert len(refs) >= 4
    for ref in refs:
        st, body, headers = c.get(ref, csrf=False)
        assert st == 200 and '<div id="app"' not in str(body), ref


def test_an_older_database_gains_the_new_client_and_lead_columns(tmp_path):
    import sqlite3

    from rankloom.db import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT, pw_hash TEXT,
                            created_at INTEGER);
        CREATE TABLE clients (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT NOT NULL,
          website TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
          niche TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', gsc_dataset INTEGER,
          created_at INTEGER NOT NULL);
        INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (1, 'a@b.co', 'A', 'x', 0);
        INSERT INTO clients (user_id, name, created_at) VALUES (1, 'Old client', 0);
        CREATE TABLE leads (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '', score INTEGER, problems TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'new', notes TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          UNIQUE(user_id, name, website));
        INSERT INTO leads (user_id, name, created_at, updated_at) VALUES (1, 'Kept lead', 0, 0);
        INSERT INTO leads (user_id, name, created_at, updated_at) VALUES (99, 'Orphan', 0, 0);
    """)
    conn.commit()
    conn.close()
    db = Database(path)
    row = db.one("SELECT name, country, work_notes, hide_fixes FROM clients")
    assert tuple(row) == ("Old client", "", "", "")
    assert db.one("SELECT name, branch FROM leads")["name"] == "Kept lead"
