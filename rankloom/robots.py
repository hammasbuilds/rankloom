"""robots.txt read the way crawlers read it: groups of user-agent lines, each with its rules, and
an agent governed by the most specific group naming it, else by the `*` group."""

from __future__ import annotations


def parse(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:  # a user-agent after rules starts a new group
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents:
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    return groups


def rules_for(text: str, agent: str) -> list[tuple[str, str]] | None:
    """The rules that apply to `agent`, or None when no group names it or `*`."""
    agent = agent.lower()
    groups = parse(text)
    named = [(len(a), r) for names, r in groups for a in names if a != "*" and a in agent]
    if named:
        return max(named, key=lambda x: x[0])[1]
    star = [r for names, r in groups if "*" in names]
    return [rule for r in star for rule in r] if star else None


def blocked(text: str, agent: str) -> bool:
    """True when the agent may not fetch the home page."""
    rules = rules_for(text, agent) or []
    disallow_root = any(k == "disallow" and v == "/" for k, v in rules)
    allow_root = any(k == "allow" and v in ("/", "/$") for k, v in rules)
    return disallow_root and not allow_root


def partial(text: str, agent: str) -> list[str]:
    """Paths disallowed for the agent short of the whole site."""
    return [v for k, v in (rules_for(text, agent) or []) if k == "disallow" and v and v != "/"]


def sitemaps(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out
