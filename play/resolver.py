"""Thin client for the WaveBeast Go engine run as a stateless resolver. Generation/battle rules live in
exactly one place (the Go engine); this site never reimplements them. Set WAVEBEAST_RESOLVER to a
co-located engine in production."""
import os

import requests

RESOLVER = os.environ.get("WAVEBEAST_RESOLVER", "http://bishop.home:8777")


def generate(bundle: dict) -> dict:
    r = requests.post(f"{RESOLVER}/generate", json=bundle, timeout=15)
    r.raise_for_status()
    return r.json()


def render(palette, recipe, shiny: bool) -> bytes:
    r = requests.post(f"{RESOLVER}/render", json={"palette": palette, "recipe": recipe, "shiny": shiny}, timeout=15)
    r.raise_for_status()
    return r.content
