"""Thin client for the WaveBeast Go engine run as a stateless resolver. Generation/battle rules live in
exactly one place (the Go engine); this site never reimplements them. Set WAVEBEAST_RESOLVER to a
co-located engine in production."""
import os

import requests

RESOLVER = os.environ.get("WAVEBEAST_RESOLVER", "http://bishop.home:8777")


def generate(bundle: dict, roll_nonce: str = "") -> dict:
    """Resolve a scan bundle to a beast. Pass roll_nonce (a server secret + random) to make the
    individual roll server-authoritative — stats the client can't predict, mod, or grind. Species stays
    deterministic from the bundle's identity regardless."""
    headers = {"X-WB-Roll-Nonce": roll_nonce} if roll_nonce else {}
    r = requests.post(f"{RESOLVER}/generate", json=bundle, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def render(palette, recipe, shiny: bool) -> bytes:
    r = requests.post(f"{RESOLVER}/render", json={"palette": palette, "recipe": recipe, "shiny": shiny}, timeout=15)
    r.raise_for_status()
    return r.content


def capabilities() -> dict:
    """Engine capabilities incl. id_version (current generation) and the natures list — used by /api/sync."""
    r = requests.get(f"{RESOLVER}/capabilities", timeout=15)
    r.raise_for_status()
    return r.json()


def shop() -> dict:
    """The item catalog (id, name, cost_kind, cost_amt, ...) — the single source of truth for prices, so
    the site validates purchases against it rather than trusting a client."""
    r = requests.get(f"{RESOLVER}/economy/shop", timeout=15)
    r.raise_for_status()
    return r.json()


def battle_auto(team_a: list, team_b: list) -> dict:
    """team_* = [{"species": {...}, "individual": {...}}, ...]. Returns {winner, turns, log}."""
    r = requests.post(f"{RESOLVER}/battle/auto", json={"a": team_a, "b": team_b}, timeout=20)
    r.raise_for_status()
    return r.json()
