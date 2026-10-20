"""GitHub: connect an account (OAuth app or a personal access token), list repositories, import one.

All traffic goes through `request()`, which tests replace, so nothing here needs the network to be
tested. Tokens are never logged and never returned to the browser; the server seals them before
they reach the database.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
OAUTH_SCOPES = "read:user repo"


class GitHubError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def request(method: str, url: str, headers: dict, body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubError(f"GitHub could not be reached: {exc}") from exc


def api(token: str, path: str) -> dict | list:
    status, raw = request(
        "GET",
        API + path,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rankloom",
        },
    )
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        data = None
    if status == 401:
        raise GitHubError("GitHub rejected the token. Check it, or make a new one, and try again.", 401)
    if status == 404:
        raise GitHubError("GitHub has no such repository, or the token cannot see it.", 404)
    if status >= 400:
        msg = data.get("message") if isinstance(data, dict) else ""
        raise GitHubError(f"GitHub answered {status}: {msg or 'error'}", status)
    return data


def oauth_client() -> tuple[str, str] | None:
    cid = os.environ.get("RANKLOOM_GITHUB_CLIENT_ID", "").strip()
    secret = os.environ.get("RANKLOOM_GITHUB_CLIENT_SECRET", "").strip()
    return (cid, secret) if cid and secret else None


def authorize_url(client_id: str, state: str, redirect_uri: str) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "state": state,
            "allow_signup": "true",
        }
    )
    return f"https://github.com/login/oauth/authorize?{q}"


def exchange_code(client_id: str, secret: str, code: str, redirect_uri: str) -> str:
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode()
    status, raw = request(
        "POST",
        "https://github.com/login/oauth/access_token",
        {
            "Accept": "application/json",
            "User-Agent": "rankloom",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
    )
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise GitHubError("GitHub sent an unreadable reply to the sign-in.") from exc
    token = data.get("access_token") if isinstance(data, dict) else None
    if status != 200 or not token:
        raise GitHubError(data.get("error_description", "GitHub refused the sign-in."), status)
    return token


def whoami(token: str) -> str:
    data = api(token, "/user")
    return str(data.get("login", "")) if isinstance(data, dict) else ""


def list_repos(token: str) -> list[dict]:
    data = api(token, "/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator")
    return [
        {
            "full_name": r["full_name"],
            "description": r.get("description") or "",
            "private": bool(r.get("private")),
            "language": r.get("language") or "",
            "updated_at": r.get("updated_at") or "",
            "stars": r.get("stargazers_count", 0),
        }
        for r in (data if isinstance(data, list) else [])
    ]


def valid_repo_name(full_name: str) -> bool:
    parts = full_name.split("/")
    ok = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    return len(parts) == 2 and all(p and set(p) <= ok and p not in (".", "..") for p in parts)


def import_repo(token: str, full_name: str) -> dict:
    if not valid_repo_name(full_name):
        raise GitHubError("A repository is written owner/name.")
    q = urllib.parse.quote
    owner, name = full_name.split("/")
    base = f"/repos/{q(owner)}/{q(name)}"
    repo = api(token, base)
    languages = api(token, base + "/languages")
    branch = repo.get("default_branch") or "main"
    files = 0
    try:
        tree = api(token, f"{base}/git/trees/{q(branch)}?recursive=1")
        files = sum(1 for t in tree.get("tree", []) if t.get("type") == "blob")
    except GitHubError as exc:
        if exc.status != 409:  # 409 = empty repository: no tree yet, not an error
            raise
    return {
        "repo": repo["full_name"],
        "description": repo.get("description") or "",
        "default_branch": branch,
        "languages": languages if isinstance(languages, dict) else {},
        "file_count": files,
        "private": bool(repo.get("private")),
    }
