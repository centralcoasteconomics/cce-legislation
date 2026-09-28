"""Build the Legislative Log data from the Legislative Counsel's nightly archive.

    python3 pipeline/build.py                # network: read the live archive
    python3 pipeline/build.py --cache .cache # keep fetched members between runs (dev)

Writes data/meta.json, data/index.json (one row per housing bill), data/bills/<slug>.json
(the full record the bill page renders) and data/changes.json (what moved since the last
run, which the steward's morning pass reads). Deterministic: no editorial text is made
here. Editorial notes live in editorial/ and are merged by the website at render time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent))
import pubinfo as P  # noqa: E402
import stages as S  # noqa: E402
import topics as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEGINFO = "https://leginfo.legislature.ca.gov/faces/"
PARTY = {"DEM": "D", "REP": "R", "IND": "I", "NPP": "NPP"}
TABLES = {
    "BILL_TBL": P.BILL, "BILL_HISTORY_TBL": P.HIST, "BILL_VERSION_TBL": P.VER,
    "BILL_VERSION_AUTHORS_TBL": P.AUTH, "BILL_SUMMARY_VOTE_TBL": P.VOTE,
    "BILL_ANALYSIS_TBL": P.ANALYSIS, "VETO_MESSAGE_TBL": P.VETO, "LOCATION_CODE_TBL": P.LOC,
    "LEGISLATOR_TBL": P.LEGISLATOR, "COMMITTEE_HEARING_TBL": P.HEARING,
}
NS = {"caml": "http://lc.ca.gov/legalservices/schemas/caml.1#"}


def day(v: str | None) -> str | None:
    return v[:10] if v else None


def slug(bill: dict) -> str:
    return f'{bill["measure_type"].lower()}-{int(bill["measure_num"])}'


def label(bill: dict) -> str:
    return f'{bill["measure_type"]} {int(bill["measure_num"])}'


def text_of(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def parse_bill_xml(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    digest = [text_of(p) for p in root.iterfind(".//caml:DigestText/{http://www.w3.org/1999/xhtml}p", NS)]
    if not digest:
        digest = [text_of(p) for p in root.iterfind(".//caml:DigestText/*", NS)]
    return {
        "title": text_of(root.find(".//caml:Title", NS)),
        "digest": [d for d in digest if d],
        "authorLine": " ".join(text_of(a) for a in root.iterfind(".//caml:AuthorText", NS)),
    }


def parse_veto(raw: bytes) -> list[str]:
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", s)]
    return [p for p in paras if p]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="directory to keep fetched archive members (dev only)")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for tests")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config/session.json").read_text())
    session = cfg["sessions"][-1]
    today = args.today or dt.date.today().isoformat()
    hc = set(cfg["housingCommittees"])
    types = set(cfg["measureTypes"])
    inc = json.loads((ROOT / "editorial/include.json").read_text()) if (ROOT / "editorial/include.json").exists() else {}
    include, exclude = set(inc.get("include", [])), set(inc.get("exclude", []))

    cache = Path(args.cache) if args.cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    arc = P.Archive(session["archiveYear"], str(cache) if cache else None)

    def fetch(names: list[str]) -> dict[str, bytes]:
        got, need = {}, []
        for n in names:
            f = cache / n if cache else None
            if f and f.exists() and cache_ok:
                got[n] = f.read_bytes()
            else:
                need.append(n)
        for n, b in arc.read_many(need).items():
            got[n] = b
            if cache:
                (cache / n).write_bytes(b)
        return got

    stamp = cache / "_etag" if cache else None
    cache_ok = bool(stamp and stamp.exists() and stamp.read_text() == (arc.etag or ""))
    raw = fetch([f"{t}.dat" for t in TABLES])
    if stamp:
        stamp.write_text(arc.etag or "")
    T_ = {t: list(P.rows(raw[f"{t}.dat"], c)) for t, c in TABLES.items()}

    bills = {b["bill_id"]: b for b in T_["BILL_TBL"]}
    loc_names = {r["location_code"]: r["long_description"] or r["description"] for r in T_["LOCATION_CODE_TBL"]}
    loc_names.update({"AFLOOR": "Assembly Floor", "SFLOOR": "Senate Floor"})
    # committee long names drop the house; put it back so "Appropriations" is unambiguous
    for r in T_["LOCATION_CODE_TBL"]:
        c = r["location_code"]
        if c.startswith("CX"):
            loc_names[c] = "Assembly " + (r["long_description"] or r["description"])
        elif c.startswith("CS"):
            loc_names[c] = "Senate " + (r["long_description"] or r["description"])

    hist = defaultdict(list)
    for h in T_["BILL_HISTORY_TBL"]:
        hist[h["bill_id"]].append(h)
    for b in hist:
        hist[b].sort(key=lambda h: (h["action_date"] or "", int(h["action_sequence"] or 0), h["bill_history_id"] or ""))

    housing = []
    for bid, b in bills.items():
        if b["measure_type"] not in types or bid in exclude:
            continue
        via = any({h["primary_location"], h["secondary_location"], h["ternary_location"]} & hc for h in hist[bid])
        if via or bid in include:
            housing.append(bid)
    housing.sort(key=lambda x: (bills[x]["measure_type"], int(bills[x]["measure_num"])))

    versions = defaultdict(list)
    vby = {}
    for v in T_["BILL_VERSION_TBL"]:
        versions[v["bill_id"]].append(v)
        vby[v["bill_version_id"]] = v
    authors = defaultdict(list)
    for a in T_["BILL_VERSION_AUTHORS_TBL"]:
        if a["active_flg"] == "Y":
            authors[a["bill_version_id"]].append(a)
    party = {}
    for l in T_["LEGISLATOR_TBL"]:
        h = {"A": "ASSEMBLY", "S": "SENATE"}.get(l["house"])
        for nm in (l["author_name"], l["last_name"]):
            if nm and h:
                party.setdefault((h, nm), PARTY.get(l["party"] or "", l["party"]))
    votes = defaultdict(list)
    for v in T_["BILL_SUMMARY_VOTE_TBL"]:
        votes[v["bill_id"]].append({
            "location_code": v["location_code"], "date": day(v["vote_date_time"]),
            "ayes": int(v["ayes"] or 0), "noes": int(v["noes"] or 0), "nvr": int(v["abstain"] or 0),
            "result": (v["vote_result"] or "").strip("()").title(),
        })
    for b in votes:
        votes[b].sort(key=lambda v: v["date"] or "")
    analyses = defaultdict(list)
    for a in T_["BILL_ANALYSIS_TBL"]:
        if a["active_flg"] == "Y":
            analyses[a["bill_id"]].append({"date": day(a["analysis_date"]), "committee": a["committee_name"],
                                           "house": {"A": "Assembly", "S": "Senate"}.get(a["house"], a["house"])})
    vetoes = {v["bill_id"]: v for v in T_["VETO_MESSAGE_TBL"]}
    hearings = defaultdict(list)
    for h in T_["COMMITTEE_HEARING_TBL"]:
        if day(h["hearing_date"]) and day(h["hearing_date"]) >= today:
            hearings[h["bill_id"]].append({"date": day(h["hearing_date"]), "committee": loc_names.get(h["location_code"], h["location_code"])})

    # latest bill text for every housing bill, and veto messages: one range read each
    lob_names = []
    for bid in housing:
        v = vby.get(bills[bid]["latest_bill_version_id"])
        if v and v["bill_xml"]:
            lob_names.append(v["bill_xml"])
        if bid in vetoes and vetoes[bid]["message"]:
            lob_names.append(vetoes[bid]["message"])
    lobs = fetch([n for n in lob_names if n in arc.members])

    prev_path = ROOT / "data/index.json"
    prev_doc = json.loads(prev_path.read_text()) if prev_path.exists() else {"meta": {}, "bills": []}
    prev = {r["id"]: r for r in prev_doc["bills"]}
    prev_at = prev_doc["meta"].get("generatedAt")

    rows, changes = [], []
    (ROOT / "data/bills").mkdir(parents=True, exist_ok=True)
    for bid in housing:
        b = bills[bid]
        v = vby.get(b["latest_bill_version_id"]) or {}
        xmlinfo = {}
        if v.get("bill_xml") in lobs:
            try:
                xmlinfo = parse_bill_xml(lobs[v["bill_xml"]])
            except ET.ParseError:
                xmlinfo = {}
        title = xmlinfo.get("title", "")
        secs = T.code_sections(title)
        area_keys = T.areas(secs, v.get("subject") or "")
        auth = []
        for a in authors.get(b["latest_bill_version_id"], []):
            nm = a["name"]
            auth.append({"name": nm, "role": a["contribution"], "house": (a["house"] or "").title(),
                         "type": a["type"], "party": party.get((a["house"], nm))})
        order = {"LEAD_AUTHOR": 0, "PRINCIPAL_COAUTHOR": 1, "COAUTHOR": 2}
        auth.sort(key=lambda a: (order.get(a["role"], 3), a["house"] != ("Assembly" if b["measure_type"].startswith("A") else "Senate")))
        tl = S.build(b, hist[bid], votes[bid], v, loc_names, stalled_after=session["stalledAfter"], today=today)
        h_rows = hist[bid]
        last = h_rows[-1] if h_rows else None
        s_ = slug(b)
        gov_deadline = None
        if tl["outcome"] == "governor":
            gov_deadline = next((c["date"] for c in cfg["calendar"] if "Governor to sign" in c["label"]), None)
        rec = {
            "id": bid, "slug": s_, "label": label(b), "type": b["measure_type"], "number": int(b["measure_num"]),
            "session": session["key"], "subject": v.get("subject") or "", "title": title,
            "authors": auth, "outcome": tl["outcome"], "current": tl["current"],
            "currentLabel": next((st["label"] for st in tl["stages"] if st["key"] == tl["current"]), None),
            "location": b["current_house"], "statusRaw": b["current_status"], "measureState": b["measure_state"],
            "lastAction": {"date": day(last["action_date"]), "text": re.sub(r"\s+", " ", last["action"]).strip()} if last else None,
            "chapter": tl["chapter"], "presented": day(tl["presented"]), "approved": day(tl["approved"]),
            "vetoed": day(tl["vetoed"]), "governorDeadline": gov_deadline,
            "areas": area_keys, "sections": secs,
            "flags": {"vote": v.get("vote_required"), "appropriation": v.get("appropriation"),
                      "fiscal": v.get("fiscal_committee"), "localProgram": v.get("local_program"),
                      "urgency": v.get("urgency"), "taxLevy": v.get("taxlevy")},
            "nextHearing": sorted(hearings.get(bid, []), key=lambda x: x["date"])[:1] or None,
            "urgency": (v.get("urgency") or "").lower() == "yes",
            "progress": sum(1 for st in tl["stages"] if st["state"] in ("done", "skipped")) / len(tl["stages"]),
        }
        full = {
            **rec,
            "digest": xmlinfo.get("digest", []),
            "authorLine": xmlinfo.get("authorLine", ""),
            "stages": [{k: (day(val) if k in ("done", "suspense", "held", "presented", "pending", "vetoed", "stoppedOn") and isinstance(val, str) else val)
                        for k, val in st.items()} for st in tl["stages"]],
            "history": [{"date": day(h["action_date"]), "text": re.sub(r"\s+", " ", h["action"]).strip(),
                         "house": h["primary_location"], "where": h["secondary_location"],
                         "event": S.classify(h)} for h in h_rows],
            "votes": [{**vv, "where": loc_names.get(vv["location_code"], vv["location_code"])} for vv in votes[bid]],
            "analyses": sorted(analyses[bid], key=lambda a: a["date"] or ""),
            "versions": [{"date": day(x["bill_version_action_date"]), "action": x["bill_version_action"], "id": x["bill_version_id"]}
                         for x in sorted(versions[bid], key=lambda x: (x["bill_version_action_date"] or "", -int(x["version_num"] or 0)))],
            "veto": parse_veto(lobs[vetoes[bid]["message"]]) if bid in vetoes and vetoes[bid]["message"] in lobs else None,
            "links": {
                "text": f"{LEGINFO}billTextClient.xhtml?bill_id={bid}",
                "status": f"{LEGINFO}billStatusClient.xhtml?bill_id={bid}",
                "history": f"{LEGINFO}billHistoryClient.xhtml?bill_id={bid}",
                "votes": f"{LEGINFO}billVotesClient.xhtml?bill_id={bid}",
                "analysis": f"{LEGINFO}billAnalysisClient.xhtml?bill_id={bid}",
                "compare": f"{LEGINFO}billCompareClient.xhtml?bill_id={bid}",
                "pdf": f"{LEGINFO}billPdf.xhtml?bill_id={bid}&version={b['latest_bill_version_id']}",
            },
        }
        (ROOT / f"data/bills/{s_}.json").write_text(json.dumps(full, ensure_ascii=False, indent=1))
        rows.append(rec)
        p = prev.get(bid)
        if p is None:
            changes.append({"id": bid, "slug": s_, "label": rec["label"], "kind": "new", "outcome": rec["outcome"]})
        elif (p["outcome"], p["current"], (p.get("lastAction") or {}).get("date")) != (rec["outcome"], rec["current"], (rec.get("lastAction") or {}).get("date")):
            changes.append({"id": bid, "slug": s_, "label": rec["label"], "kind": "moved",
                            "from": {"outcome": p["outcome"], "current": p["current"]},
                            "to": {"outcome": rec["outcome"], "current": rec["current"]},
                            "lastAction": rec["lastAction"]})

    from collections import Counter
    counts = Counter(r["outcome"] for r in rows)
    meta = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "today": today,
        "session": session, "source": {"archive": arc.url, "lastModified": arc.last_modified, "etag": arc.etag,
                                       "publisher": "Legislative Counsel of California"},
        "fetchedBytes": arc.fetched, "counts": dict(counts), "total": len(rows),
        "definition": "Every Assembly and Senate bill and constitutional amendment of the session that was referred to the Assembly Housing and Community Development Committee or the Senate Housing Committee, plus any bill added by hand in editorial/include.json.",
        "calendar": cfg["calendar"], "areas": T.AREA_LABEL,
    }
    (ROOT / "data/index.json").write_text(json.dumps({"meta": meta, "bills": rows}, ensure_ascii=False, indent=1))
    (ROOT / "data/meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    (ROOT / "data/changes.json").write_text(json.dumps({"generatedAt": meta["generatedAt"], "since": prev_at, "changes": changes}, ensure_ascii=False, indent=1))
    live = {s_.stem for s_ in (ROOT / "data/bills").glob("*.json")}
    for gone in live - {r["slug"] for r in rows}:
        (ROOT / f"data/bills/{gone}.json").unlink()
    print(f"{len(rows)} housing bills · {dict(counts)} · {len(changes)} changes · fetched {arc.fetched / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
