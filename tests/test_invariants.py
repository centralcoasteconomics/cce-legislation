"""Invariants over a built data/ directory. Run after every build (the nightly job does):

    python3 tests/test_invariants.py

Each check is a statement a reader of the trackline relies on. A failure means the stage
model drew something false about a real bill, which is worse than drawing nothing.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
idx = json.loads((ROOT / "data/index.json").read_text())
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


bills = idx["bills"]
check(len(bills) >= 50, f"only {len(bills)} housing bills; the committee rule or the archive broke")
for r in bills:
    b = json.loads((ROOT / f"data/bills/{r['slug']}.json").read_text())
    st = b["stages"]
    states = [s["state"] for s in st]
    lbl = r["label"]
    check(states.count("current") + states.count("failed") + states.count("stalled") <= 1,
          f"{lbl}: more than one live stage {states}")
    check(st[0]["state"] == "done", f"{lbl}: not marked introduced")
    # nothing is done after the live stage
    live = next((i for i, s in enumerate(st) if s["state"] in ("current", "failed", "stalled")), None)
    if live is not None:
        check(all(s["state"] in ("upcoming", "skipped") for s in st[live + 1:]),
              f"{lbl}: a stage after the live one is done {states}")
    # done dates never go backwards
    dates = [s["done"] for s in st if s["state"] == "done" and s["done"]]
    check(dates == sorted(dates), f"{lbl}: done dates out of order {dates}")
    o = r["outcome"]
    gov = next((s for s in st if s["kind"] == "governor"), None)
    if o == "governor":
        check(gov and gov["state"] == "current" and gov.get("presented"), f"{lbl}: at Governor but stage is {gov and gov['state']}")
        check(r["governorDeadline"], f"{lbl}: at Governor with no deadline")
    if o == "law":
        check(r["chapter"] or r["approved"], f"{lbl}: law without a chapter or approval")
        check(all(s["state"] in ("done", "skipped", "current") for s in st), f"{lbl}: law with a failed stage {states}")
    if o == "vetoed":
        check(gov and gov["state"] == "failed" and gov.get("stoppedOn"), f"{lbl}: vetoed but Governor stage is {gov and gov['state']}")
    if o in ("died", "stalled"):
        check(live is not None and st[live]["state"] in ("failed", "stalled") and st[live].get("reason"),
              f"{lbl}: {o} without a stopped stage and reason")
    for s in st:
        if s["kind"] == "floor" and s["state"] == "done":
            check(s.get("vote") and s["vote"]["ayes"] > s["vote"]["noes"], f"{lbl}: floor passed with vote {s.get('vote')}")
    check(b["links"]["status"].endswith(r["id"]), f"{lbl}: status link does not point at the bill")

if fails:
    print(f"{len(fails)} invariant failures:")
    for f in fails[:40]:
        print("  -", f)
    sys.exit(1)
print(f"OK: {len(bills)} bills, every trackline consistent")
