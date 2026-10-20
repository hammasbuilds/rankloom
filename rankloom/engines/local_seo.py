"""Local SEO Check: does a business page tell search engines and maps who, where and how to reach
it - LocalBusiness data, name/address/phone on the page and in the data agreeing, click-to-call,
a map, the Google Business Profile, reviews, hours, WhatsApp."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import market
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    check,
    checks,
    facts,
    headline,
    score_checks,
    sort_checks,
    view,
)
from .site_audit import (
    blocked_result,
    blocked_view,
    challenge,
    jsonld_objects,
    normalise_url,
    parse_page,
)

# schema.org LocalBusiness and the subtypes small businesses actually use
LOCAL_TYPES = {
    "localbusiness",
    "dentist",
    "physician",
    "medicalbusiness",
    "medicalclinic",
    "hospital",
    "pharmacy",
    "optician",
    "restaurant",
    "foodestablishment",
    "cafeorcoffeeshop",
    "bakery",
    "store",
    "clothingstore",
    "electronicsstore",
    "furniturestore",
    "grocerystore",
    "hardwarestore",
    "homegoodsstore",
    "jewelrystore",
    "autorepair",
    "autodealer",
    "automotivebusiness",
    "beautysalon",
    "hairsalon",
    "dayspa",
    "healthclub",
    "lodgingbusiness",
    "hotel",
    "realestateagent",
    "legalservice",
    "attorney",
    "accountingservice",
    "financialservice",
    "insuranceagency",
    "educationalorganization",
    "school",
    "childcare",
    "homeandconstructionbusiness",
    "electrician",
    "plumber",
    "hvacbusiness",
    "roofingcontractor",
    "generalcontractor",
    "housepainter",
    "locksmith",
    "movingcompany",
    "professionalservice",
    "travelagency",
    "veterinarycare",
    "sportsactivitylocation",
    "entertainmentbusiness",
    "emergencyservice",
    "governmentoffice",
    "library",
}
# The opening bracket belongs to the number ("(716) 689-8882"), and a number never runs across a
# line break: "716)\n689-8882\n777" was a phone, then the street number of the next line. Nor
# does it start inside another number: "24/7 512-400-0749" is not "7 512-400-0749".
PHONE = re.compile(r"(?<![\w/])(?:\+|\()?\d[\d \t().-]{7,}\d")
MAP_HINTS = (
    "google.com/maps",
    "maps.google",
    "goo.gl/maps",
    "maps.app.goo.gl",
    "openstreetmap.org",
    "bing.com/maps",
    "waze.com",
)
PROFILE_HINTS = (
    "g.page",
    "maps.app.goo.gl",
    "google.com/maps/place",
    "goo.gl/maps",
    "search.google.com/local",
    "business.google.com",
)
# Pages where reviews are read or written. A plain Facebook page is not one: it passed Pizzeria
# Bianco's review check on facebook.com/biancorestaurants/ alone.
REVIEW_HINTS = (
    "writereview",
    "search.google.com/local/reviews",
    "trustpilot.com",
    "yelp.",
    "tripadvisor.",
    "zocdoc.com",
    "healthgrades.com",
    "opentable.com",
    "/review",
)
# Calling codes and domain endings that say which country a business is in.
CALLING = (
    ("+971", "ae"),
    ("+966", "sa"),
    ("+974", "qa"),
    ("+965", "kw"),
    ("+973", "bh"),
    ("+968", "om"),
    ("+353", "ie"),
    ("+92", "pk"),
    ("+44", "gb"),
    ("+91", "in"),
    ("+60", "my"),
    ("+65", "sg"),
    ("+61", "au"),
    ("+64", "nz"),
    ("+49", "de"),
    ("+33", "fr"),
    ("+34", "es"),
    ("+31", "nl"),
    ("+1", "us"),
)
TLD = {"uk": "gb", **{c: c for c in market.NAMES if c not in ("us", "gb")}}
US_STATES = set(
    "al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj "
    "nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc".split()
)


def detect_country(biz: dict | None, tel_links: list[str], final_url: str) -> tuple[str, str]:
    """(country code, how it was found), or ("", "") when the page does not say."""
    addr = (biz or {}).get("address") or {}
    if isinstance(addr, list):
        addr = addr[0] if addr else {}
    if isinstance(addr, dict):
        c = addr.get("addressCountry")
        c = (c.get("name") or c.get("@id") or "") if isinstance(c, dict) else str(c or "")
        low = c.strip().lower()
        by_name = {n.lower(): k for k, n in market.NAMES.items()}
        hit = low if low in market.NAMES else "gb" if low == "uk" else by_name.get(low, "")
        if hit:
            return hit, "the address data"
        if str(addr.get("addressRegion", "")).strip().lower() in US_STATES:
            return "us", "the state in the address data"
    for number in [str((biz or {}).get("telephone", ""))] + [t[4:] for t in tel_links]:
        n = re.sub(r"[^\d+]", "", number)
        if n.startswith("00"):
            n = "+" + n[2:]
        for prefix, cc in CALLING:
            if n.startswith(prefix):
                return cc, "the phone number's country code"
    host = urlsplit(final_url).hostname or ""
    tld = host.rsplit(".", 1)[-1]
    if tld in TLD:
        return TLD[tld], f"the .{tld} web address"
    return "", ""


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s)
    if d.startswith("0092"):
        d = d[4:]
    elif d.startswith("92") and len(d) >= 11:
        d = d[2:]
    return d.lstrip("0")


def _types(obj: dict) -> set[str]:
    t = obj.get("@type")
    items = t if isinstance(t, list) else [t]
    return {str(x).lower() for x in items if x}


def audit(url: str, city: str, fetch, country: str = "") -> dict:
    url = normalise_url(url)
    resp = fetch(url)
    page = parse_page(resp.text())
    blocked = challenge(resp, page)
    if blocked:
        return {**blocked_result(url, resp, blocked), "business": None, "market": ""}
    text = page.text
    lowered_links = [h.lower() for h in page.anchors]
    objs = jsonld_objects(page.jsonld)
    biz = next((o for o in objs if _types(o) & LOCAL_TYPES), None)
    org = biz or next((o for o in objs if _types(o) & {"organization"}), None)
    items: list[dict] = []

    items.append(
        check(
            "schema",
            "LocalBusiness structured data",
            PASS if biz else WARN if org else FAIL,
            f"Found {', '.join(sorted(_types(biz)))}."
            if biz
            else "Only Organization data, not LocalBusiness."
            if org
            else "No LocalBusiness data.",
            "Add JSON-LD of the most specific LocalBusiness type (e.g. Dentist, Restaurant) with "
            "name, address, telephone, opening hours and geo.",
            3,
        )
    )

    addr = (biz or {}).get("address") or {}
    if isinstance(addr, list):
        addr = addr[0] if addr else {}
    addr_text = (
        addr
        if isinstance(addr, str)
        else " ".join(
            str(addr.get(k, "")) for k in ("streetAddress", "addressLocality", "addressRegion")
        )
    )
    has_nap = bool(biz and biz.get("name") and addr_text.strip() and biz.get("telephone"))
    missing = ", ".join(
        k
        for k, ok in (
            ("name", (biz or {}).get("name")),
            ("address", addr_text.strip()),
            ("telephone", (biz or {}).get("telephone")),
        )
        if not ok
    )
    # With no LocalBusiness block there is nothing to be missing *from*; saying "missing: name"
    # beside an Organization that names the business reads as a contradiction.
    if has_nap:
        nap_detail = "All three present."
    elif biz:
        nap_detail = f"The LocalBusiness data is missing: {missing}."
    else:
        nap_detail = "There is no LocalBusiness data to hold them" + (
            f" (the Organization data names {org.get('name')})." if (org or {}).get("name") else "."
        )
    items.append(
        check(
            "nap-data",
            "Name, address and phone in the data",
            PASS if has_nap else FAIL if biz else WARN,
            nap_detail,
            "Fill name, a PostalAddress (street, city) and telephone in the LocalBusiness data.",
            2,
        )
    )

    phones = [
        " ".join(p.split()) for p in PHONE.findall(text) if 9 <= len(re.sub(r"\D", "", p)) <= 15
    ]
    phones = list(dict.fromkeys(phones))
    tel_links = [h for h in page.anchors if h.lower().startswith("tel:")]
    items.append(
        check(
            "phone",
            "Phone number visible on the page",
            PASS if phones or tel_links else FAIL,
            f"Found {phones[0].strip()}."
            if phones
            else "Only in a tel: link."
            if tel_links
            else "No phone number in the page text.",
            "Show the phone number as text on every page, usually in the header or footer.",
            2,
        )
    )
    items.append(
        check(
            "click-to-call",
            "Click-to-call link",
            PASS if tel_links else WARN,
            tel_links[0] if tel_links else "No tel: link.",
            'Wrap the number in <a href="tel:+...">, with the country code, so a phone visitor '
            "can call in one tap.",
        )
    )

    data_phone = _digits(str((biz or {}).get("telephone", "")))
    page_phones = {_digits(p) for p in phones} | {_digits(t[4:]) for t in tel_links}
    if data_phone:
        agree = any(data_phone[-9:] == p[-9:] for p in page_phones if len(p) >= 9)
        items.append(
            check(
                "nap-match",
                "Phone in the data matches the page",
                PASS if agree else FAIL,
                "The same number appears in both."
                if agree
                else f"The data says {biz.get('telephone')}, which is not on the page.",
                "Use one phone number everywhere: page, structured data and Google profile.",
                2,
            )
        )

    street = str(addr.get("streetAddress", "")) if isinstance(addr, dict) else str(addr)
    addr_on_page = bool(street) and street.lower()[:18] in text.lower()
    items.append(
        check(
            "address",
            "Address visible on the page",
            PASS if addr_on_page else WARN,
            "The street address in the data is in the page text."
            if addr_on_page
            else "Could not find the street address in the page text.",
            "Print the full address as text (not only inside an image or map).",
        )
    )

    maps = [s for s in page.iframes + page.anchors if any(h in s.lower() for h in MAP_HINTS)]
    items.append(
        check(
            "map",
            "Map or directions link",
            PASS if maps else WARN,
            "Found a map or directions link." if maps else "No map embed or directions link.",
            "Embed a map or link to directions so visitors can find you.",
        )
    )
    profile = [h for h in lowered_links if any(p in h for p in PROFILE_HINTS)]
    items.append(
        check(
            "profile",
            "Links to the Google Business Profile",
            PASS if profile else WARN,
            profile[0] if profile else "No link to a Google Business Profile.",
            "Link to your Google Business Profile; it is the main source maps and local results "
            "use.",
            2,
        )
    )
    rating = next((o.get("aggregateRating") for o in objs if o.get("aggregateRating")), None)
    review_links = [h for h in lowered_links if any(p in h for p in REVIEW_HINTS)]
    items.append(
        check(
            "reviews",
            "Reviews shown or asked for",
            PASS if rating or review_links else WARN,
            "Rating data present."
            if rating
            else "Links to a review page."
            if review_links
            else "No reviews on the page and no link asking for one.",
            "Show your review score and link to your Google review page.",
        )
    )
    hours = bool(biz and (biz.get("openingHours") or biz.get("openingHoursSpecification")))
    items.append(
        check(
            "hours",
            "Opening hours in the data",
            PASS if hours else WARN,
            "Opening hours present." if hours else "No opening hours in the data.",
            "Add openingHoursSpecification so search can say whether you are open now.",
        )
    )
    geo = bool(biz and biz.get("geo"))
    items.append(
        check(
            "geo",
            "Map coordinates in the data",
            PASS if geo else WARN,
            "geo present." if geo else "No geo coordinates.",
            "Add geo latitude and longitude to the LocalBusiness data.",
        )
    )
    same_as = (org or {}).get("sameAs") or []
    items.append(
        check(
            "same-as",
            "Social profiles linked in the data",
            PASS if same_as else WARN,
            f"{len(same_as) if isinstance(same_as, list) else 1} profile(s) in sameAs."
            if same_as
            else "No sameAs links.",
            "List your Facebook, Instagram and LinkedIn pages in sameAs.",
        )
    )
    chosen = (country or "").strip().lower()
    cc, how = (
        (chosen, "your choice")
        if chosen in market.NAMES
        else detect_country(biz, tel_links, resp.url)
    )
    # WhatsApp is how customers reach a business first in Pakistan and the Gulf, not in the US
    # or the UK; telling a dentist in New York to add it cost points and reached their report.
    wa = [h for h in lowered_links if "wa.me/" in h or "api.whatsapp.com" in h]
    if cc in market.WHATSAPP_FIRST:
        items.append(
            check(
                "whatsapp",
                "WhatsApp contact link",
                PASS if wa else WARN,
                wa[0] if wa else "No WhatsApp link.",
                f"Add a wa.me link; in {market.NAMES[cc]} many customers message before calling.",
            )
        )
    if city:
        c = city.lower()
        where = [
            w
            for w, s in (
                ("title", page.title or ""),
                ("H1", " ".join(t for lv, t in page.headings if lv == 1)),
            )
            if c in s.lower()
        ]
        items.append(
            check(
                "city",
                f"{city} named in the title or H1",
                PASS if where else WARN,
                f"In the {' and '.join(where)}." if where else f"{city} is in neither.",
                f"Put {city} in the page title and main heading of the location page.",
                2,
            )
        )

    items = sort_checks(items)
    score, counts = score_checks(items)
    return {
        "url": url,
        "final_url": resp.url,
        "score": score,
        "counts": counts,
        "checks": items,
        "market": cc,
        "market_how": how,
        "business": {
            "name": (biz or org or {}).get("name", ""),
            "phone": phones[:3],
            "data_phone": (biz or {}).get("telephone", ""),
            "address": addr_text.strip(),
        },
    }


def run(fields: dict, ctx: Context) -> tuple[str, int, dict]:
    r = audit(
        str(fields.get("url", "")),
        str(fields.get("city", "")).strip(),
        ctx.fetch,
        str(fields.get("country", "")),
    )
    if r.get("blocked"):
        r["view"] = blocked_view(r, "business page")
        return f"{r['final_url']}: could not read the real page ({r['blocked']})", None, r
    b = r["business"]
    where = (
        f"{market.NAMES[r['market']]} (from {r['market_how']})"
        if r["market"]
        else "Not stated on the page - choose the country to check WhatsApp advice"
    )
    r["view"] = view(
        headline(r["final_url"], "Local search and maps readiness", r["score"], r["counts"]),
        facts(
            "What the page says about the business",
            [
                ("Name in data", b["name"] or "-"),
                ("Phone on page", ", ".join(b["phone"]) or "-"),
                ("Phone in data", b["data_phone"] or "-"),
                ("Address in data", b["address"] or "-"),
                ("Country", where),
            ],
        ),
        checks("Checks", r["checks"]),
    )
    c = r["counts"]
    return (
        f"{r['final_url']} local score {r['score']}/100 - {c['fail']} fail, {c['warn']} warn",
        r["score"],
        r,
    )
