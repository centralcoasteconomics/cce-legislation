"""Gate on the only human-written text in this repo. The steward's morning pass must exit 0
here before it commits:

    python3 tests/verify_editorial.py

Checks: valid JSON; every watch item and note points at a bill in data/; at most six watch
items; dated fields are ISO dates; no em or en dashes (house style); nothing that names
Many Mansions or its projects (Rule #0: CCE is a separate venture); no endorsement words.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
slugs = {r["slug"] for r in json.loads((ROOT / "data/index.json").read_text())["bills"]}
fails = []
DENY = re.compile(r"many mansions|\bMM\b|rancho sierra|mountain view ii|gateway grove|juniper crossing", re.I)
ADVOCACY = re.compile(r"\b(we support|we oppose|should pass|should be vetoed|urge|vote yes|vote no|good bill|bad bill)\b", re.I)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def text_of(o):
    if isinstance(o, dict):
        return " ".join(text_of(v) for k, v in o.items() if not k.startswith("_"))
    if isinstance(o, list):
        return " ".join(text_of(v) for v in o)
    return str(o) if isinstance(o, str) else ""


docs = {}
for f in ("watch.json", "notes.json", "ballot.json", "include.json"):
    p = ROOT / "editorial" / f
    try:
        docs[f] = json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        fails.append(f"{f}: not valid JSON ({e})")
        continue
    t = text_of(docs[f])
    if re.search("[–—]", t):
        fails.append(f"{f}: contains an em or en dash")
    if DENY.search(t):
        fails.append(f"{f}: names Many Mansions or one of its projects ({DENY.search(t).group(0)})")
    if ADVOCACY.search(t):
        fails.append(f"{f}: reads as a position ({ADVOCACY.search(t).group(0)})")

w = docs.get("watch.json", {})
items = w.get("items", [])
if len(items) > 6:
    fails.append(f"watch.json: {len(items)} items; keep six or fewer")
for it in items:
    if it.get("slug") not in slugs:
        fails.append(f"watch.json: {it.get('slug')} is not a housing bill in data/")
    if not it.get("why"):
        fails.append(f"watch.json: {it.get('slug')} has no `why`")
if w.get("updated") and not ISO.match(w["updated"]):
    fails.append("watch.json: `updated` is not YYYY-MM-DD")
for k, v in docs.get("notes.json", {}).items():
    if k.startswith("_"):
        continue
    if k not in slugs:
        fails.append(f"notes.json: {k} is not a housing bill in data/")
    if not ISO.match(str(v.get("updated", ""))):
        fails.append(f"notes.json: {k} has no ISO `updated`")
b = docs.get("ballot.json", {})
for m in b.get("measures", []):
    if not m.get("sources"):
        fails.append(f"ballot.json: Prop {m.get('number')} cites no source")

if fails:
    print(f"{len(fails)} editorial problem(s):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"OK: editorial clean ({len(items)} watch items, {len([k for k in docs.get('notes.json', {}) if not k.startswith('_')])} notes, {len(b.get('measures', []))} ballot measures)")
