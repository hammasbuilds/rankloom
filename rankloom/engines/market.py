"""Which country a run is for, and the places and terms that belong to other markets.

Autocomplete answers for the country it is asked about, and a lookup without a city ("how much
dentist") comes back full of the default market's places: a dentist in Williamsville, NY was
handed "dentist lahore" and "How much dentist earn in pakistan?". So every run that reads
autocomplete takes a country, and a phrasing that names a place or a market-only term from
another country - or another city of the same country, when a city was given - is dropped.

The lists are short on purpose: the places autocomplete actually returned, not a gazetteer. A
place that is not listed is kept, which errs on the side of showing a real search.
"""

from __future__ import annotations

import re

# (code, name) - the order a country picker shows them in.
COUNTRIES = (
    ("pk", "Pakistan"),
    ("ae", "United Arab Emirates"),
    ("sa", "Saudi Arabia"),
    ("qa", "Qatar"),
    ("kw", "Kuwait"),
    ("bh", "Bahrain"),
    ("om", "Oman"),
    ("gb", "United Kingdom"),
    ("us", "United States"),
    ("ca", "Canada"),
    ("au", "Australia"),
    ("ie", "Ireland"),
    ("nz", "New Zealand"),
    ("de", "Germany"),
    ("fr", "France"),
    ("es", "Spain"),
    ("nl", "Netherlands"),
    ("sg", "Singapore"),
    ("my", "Malaysia"),
    ("in", "India"),
)
NAMES = dict(COUNTRIES)
# Where customers message a business on WhatsApp before they call it.
WHATSAPP_FIRST = {"pk", "ae", "sa", "qa", "kw", "bh", "om", "in", "my"}

# Words that name a country, or a term only searched in that market ("nhs", "bank holiday").
_COUNTRY_WORDS = {
    "pk": "pakistan pakistani",
    "ae": "uae emirates",
    "sa": "saudi ksa",
    "qa": "qatar",
    "kw": "kuwait",
    "bh": "bahrain",
    "om": "oman",
    "gb": "uk england scotland wales britain british nhs|bank holiday|bank holidays|united kingdom",
    "us": "usa america american|united states",
    "ca": "canada canadian",
    "au": "australia australian",
    "ie": "ireland irish",
    "nz": "zealand",
    "de": "germany german deutschland",
    "fr": "france french",
    "es": "spain spanish tenerife",
    "nl": "netherlands dutch holland",
    "sg": "singapore",
    "my": "malaysia malaysian",
    "in": "india indian",
}
_CITIES = {
    "pk": "lahore karachi islamabad rawalpindi faisalabad multan peshawar quetta sialkot "
    "gujranwala gulberg clifton dha|johar town|bahria town|model town",
    "ae": "dubai sharjah ajman|abu dhabi|al ain",
    "sa": "riyadh jeddah dammam makkah mecca medina",
    "qa": "doha",
    "gb": "london manchester liverpool birmingham leeds glasgow edinburgh bristol sheffield "
    "cardiff belfast newcastle nottingham leicester",
    "us": "nyc brooklyn manhattan queens chicago houston dallas austin phoenix philadelphia "
    "seattle boston miami atlanta denver orlando|new york city|los angeles|fort worth|"
    "san antonio|san diego|san jose|las vegas",
    "ca": "toronto vancouver montreal calgary ottawa",
    "au": "sydney melbourne brisbane perth adelaide",
    "ie": "dublin",
    "es": "madrid barcelona marbella|costa adeje",
    "in": "delhi mumbai bangalore bengaluru chennai kolkata pune|new delhi",
    "my": "penang|kuala lumpur",
}


def _places() -> list[tuple[str, str, str]]:
    out = []
    for kind, table in (("country", _COUNTRY_WORDS), ("city", _CITIES)):
        for cc, spec in table.items():
            singles, *multi = spec.split("|")
            for w in singles.split():
                out.append((w, cc, kind))
            for m in multi:
                out.append((m.strip(), cc, kind))
    # Longest first, so "new york city" is found before anything inside it.
    return sorted(out, key=lambda p: -len(p[0]))


PLACES = _places()
_PATTERNS = [(re.compile(rf"(?<![a-z]){re.escape(p)}(?![a-z])"), p, cc, k) for p, cc, k in PLACES]


def code(value: str, default: str = "pk") -> str:
    v = (value or "").strip().lower()
    return v if v in NAMES else default


def places_in(phrase: str) -> list[tuple[str, str, str]]:
    low = " ".join(re.sub(r"[^a-z0-9]+", " ", phrase.lower()).split())
    found, taken = [], low
    for rx, place, cc, kind in _PATTERNS:
        if rx.search(taken):
            found.append((place, cc, kind))
            taken = rx.sub(" ", taken)
    return found


def foreign(phrase: str, country: str, city: str = "") -> bool:
    """True when the phrase names another market's place or term, or - when a city was given -
    another city of the same country."""
    target = " ".join(re.sub(r"[^a-z0-9]+", " ", city.lower()).split())
    for place, cc, kind in places_in(phrase):
        if target and (place in target or target in place):
            continue
        if cc != country:
            return True
        if kind == "city" and target:
            return True
    return False


def names_a_place(phrase: str) -> bool:
    return bool(places_in(phrase))
