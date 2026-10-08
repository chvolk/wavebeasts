"""Beast memories and descriptive personality; never changes combat stats."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from .models import OwnedBeast


@lru_cache(maxsize=1)
def vocabulary():
    return json.loads((Path(__file__).parent / "files/journal-traits.json").read_text())


def traits(beast):
    identity = (
        (beast.individual_json or {}).get("id") or beast.source_id or str(beast.pk)
    )
    digest = hashlib.sha256((str(identity) + "|" + beast.species_id).encode()).digest()
    words = vocabulary()
    return {
        key: words[pool][digest[i] % len(words[pool])]
        for i, (key, pool) in enumerate(
            [
                ("temperament", "temperaments"),
                ("quirk", "quirks"),
                ("signature", "signatures"),
            ]
        )
    }


def profile(beast):
    data = beast.journal_data or {}
    origin = data.get("origin") or {
        "at": beast.caught_at.isoformat(),
        "device": "Not recorded",
        "signals": [],
        "legacy": True,
    }
    return {
        "favorite": beast.favorite,
        "notes": beast.field_notes,
        "traits": traits(beast),
        "origin": origin,
        "events": list(reversed(data.get("events", [])[-100:])),
        "battles": data.get("battles", 0),
        "wins": data.get("wins", 0),
        "flavor_only": True,
    }


@transaction.atomic
def remember(beast, kind, text, win=None):
    b = OwnedBeast.objects.select_for_update().filter(pk=beast.pk).first()
    if not b:
        return
    data = dict(b.journal_data or {})
    events = list(data.get("events", []))
    events.append(
        {"at": timezone.now().isoformat(), "kind": kind, "text": str(text)[:240]}
    )
    data["events"] = events[-100:]
    if win is not None:
        data["battles"] = data.get("battles", 0) + 1
        data["wins"] = data.get("wins", 0) + int(win)
    b.journal_data = data
    b.save(update_fields=["journal_data"])
    beast.journal_data = data


def goals(beasts):
    beasts = list(beasts)
    types = {t for b in beasts for t in (b.species_json or {}).get("types", [])}
    return [
        {"label": "Grow your collection", "value": min(10, len(beasts)), "target": 10},
        {
            "label": "Discover every element",
            "value": len(
                types
                & set(
                    [
                        "ember",
                        "tide",
                        "leaf",
                        "spark",
                        "stone",
                        "gale",
                        "frost",
                        "shade",
                        "lumen",
                    ]
                )
            ),
            "target": 9,
        },
        {
            "label": "Find a shiny companion",
            "value": int(any(b.shiny for b in beasts)),
            "target": 1,
        },
        {
            "label": "Choose a favorite",
            "value": int(any(b.favorite for b in beasts)),
            "target": 1,
        },
    ]
