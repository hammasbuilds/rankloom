"""Free public data the tools read: search-box autocomplete and OpenStreetMap's place search.

Both are fixed public hosts, not addresses a user typed, so they are fetched directly. Each call
returns what it got and from where; a provider that does not answer is skipped and the caller is
told how many of its requests were answered, so a thin result is never mistaken for a full one.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Rankloom/0.1 (+https://github.com/hammasbuilds/rankloom)"


class SourceFailed(Exception):
    pass


def get_json(url: str, timeout: float = 25.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceFailed(str(exc)) from exc
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise SourceFailed("not JSON") from exc


# --- autocomplete ------------------------------------------------------------------------------

SUGGEST = {
    "google": "https://suggestqueries.google.com/complete/search?client=firefox&hl={hl}&gl={gl}&q={q}",
    "bing": "https://api.bing.com/osjson.aspx?query={q}&market={hl}-{gl}",
    "duckduckgo": "https://duckduckgo.com/ac/?q={q}&type=list&kl={gl}-{hl}",
}


def suggest(query: str, country: str = "pk", language: str = "en") -> tuple[str, list[str]]:
    """Autocomplete phrasings for `query`: (provider that answered, suggestions)."""
    q = urllib.parse.quote(query)
    last = "no provider answered"
    for name, pattern in SUGGEST.items():
        try:
            data = get_json(pattern.format(q=q, hl=language.lower(), gl=country.lower()))
        except SourceFailed as exc:
            last = f"{name}: {exc}"
            continue
        if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
            return name, [str(s) for s in data[1] if isinstance(s, str)]
    raise SourceFailed(last)


# --- OpenStreetMap place search ----------------------------------------------------------------

_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]


def places(trade: str, city: str, limit: int = 50, country: str = "") -> list[dict]:
    """Businesses of a trade in a city from OpenStreetMap's Nominatim, at most one request a
    second as its usage policy asks."""
    q = urllib.parse.quote(f"{trade} in {city}")
    url = (
        f"https://nominatim.openstreetmap.org/search?q={q}&format=jsonv2&extratags=1"
        f"&addressdetails=1&limit={min(limit, 50)}"
        # One spelling per city: without it Lahore leads came back as "Lahore", "لاہور" and
        # "لاہور کینٹ", and a Lead List search for Lahore found 23 of 42.
        "&accept-language=en"
    )
    code = country.strip().lower()
    if len(code) == 2 and code.isalpha():  # one country, so "Manchester" means one city
        url += f"&countrycodes={code}"
    with _nominatim_lock:
        wait = 1.1 - (time.monotonic() - _nominatim_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            data = get_json(url, timeout=40)
        finally:
            _nominatim_last[0] = time.monotonic()
    out = []
    for item in data if isinstance(data, list) else []:
        tags = item.get("extratags") or {}
        addr = item.get("address") or {}

        def tag(key: str, _tags=tags) -> str:
            return str(_tags.get(key) or _tags.get(f"contact:{key}") or "").strip()

        name = str(item.get("name") or "").strip()
        if not name:
            continue
        street = " ".join(x for x in (addr.get("house_number"), addr.get("road")) if x)
        area = addr.get("suburb") or addr.get("neighbourhood") or ""
        out.append(
            {
                "name": name,
                "category": str(item.get("type") or item.get("category") or ""),
                "website": tag("website").split(";")[0].strip(),
                # A chain branch often has no website tag of its own but names its brand.
                "brand": tag("brand"),
                "brand_website": tag("brand:website").split(";")[0].strip(),
                "phone": tag("phone").split(";")[0].strip(),
                "email": tag("email"),
                "address": ", ".join(x for x in (street, area) if x),
                "city": str(addr.get("city") or addr.get("town") or city),
                "region": ", ".join(str(x) for x in (addr.get("state"), addr.get("country")) if x),
                "source": f"OpenStreetMap {item.get('osm_type', '')}/{item.get('osm_id', '')}",
            }
        )
    return out
