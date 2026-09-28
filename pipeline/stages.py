"""Turn a bill's official action history into the trackline: an ordered list of stages,
each done / current / upcoming / skipped / failed / stalled, with dates and votes.

The stages follow the California path, not leginfo's reading-by-reading rail:

    introduced > policy committee > Appropriations > floor      (house of origin)
               > policy committee > Appropriations > floor      (second house)
               > concurrence > Governor > chaptered

Readings (first, second, third) stay in the history; the stage is what a practitioner
asks about ("is it out of Approps?"). Every rule here reads the Legislative Counsel's own
location codes first and the action text second; the text is only used for events that
have no code of their own (suspense file, approved, vetoed, chaptered).
"""
from __future__ import annotations

import re

APPR = {"CX25", "CS61"}
RULES = {"CX20", "CS58"}
FLOOR = {"AFLOOR": "Assembly", "SFLOOR": "Senate"}

# "Read third time. Passed." / "Read third time, passed" / "Read third time. Urgency clause
# adopted. Passed." (urgency bills, which take effect on signature). Never "Read third time
# and amended. Ordered to second reading.", which is an amendment on the floor, not a vote.
RE_FLOOR_PASS = re.compile(r"read third time\b(?:(?!ordered to second reading).){0,60}?\bpassed\b", re.I)
RE_FLOOR_FAIL = re.compile(r"read third time\b.{0,60}?\bfailed\b", re.I)
RE_VOTE = re.compile(r"\(Ayes\s*(\d+)\.\s*Noes\s*(\d+)\.", re.I)
RE_CHAPTER = re.compile(r"Chapter\s+(\d+),\s*Statutes of\s+(\d{4})", re.I)

STAGE_LABEL = {
    "introduced": "Introduced",
    "policy": "Policy committee",
    "fiscal": "Appropriations",
    "floor": "Floor vote",
    "concurrence": "Concurrence",
    "governor": "Governor",
    "chaptered": "Chaptered",
    "sos": "Secretary of State",
    "ballot": "On a ballot",
}


def other(house: str) -> str:
    return "Senate" if house == "Assembly" else "Assembly"


def classify(h: dict) -> str | None:
    a = h["action"] or ""
    al = a.lower()
    if "read first time" in al:
        return "first_read"
    if "chaptered by secretary of state" in al:
        return "chaptered"
    if "approved by the governor" in al or "approved by governor" in al:
        return "approved"
    if re.search(r"vetoed by (the )?governor", al):
        return "vetoed"
    if "enrolled and presented to the governor" in al:
        return "enrolled"
    if "amendments concurred in" in al:
        return "concurred"
    if "concurrence in" in al and "pending" in al:
        return "concur_pending"
    if RE_FLOOR_FAIL.search(a):
        return "floor_fail"
    if RE_FLOOR_PASS.search(a):
        return "floor_pass"
    if "held under submission" in al or "held in committee" in al:
        return "held"
    if "suspense file" in al:
        return "suspense"
    if al.startswith("from committee:") and ("do pass" in al or "be ordered to second reading" in al or "be adopted" in al):
        return "cmte_pass"
    if "died pursuant" in al or "joint rule 56" in al or "died at desk" in al or "died on" in al:
        return "died"
    if "referred to" in al or "re-referred to" in al:
        return "referred"
    return None


def build(bill: dict, hist: list[dict], votes: list[dict], version: dict | None,
          loc_names: dict, *, stalled_after: str | None, today: str) -> dict:
    """Return {stages, status, current, origin}.

    `stalled_after` is the last day any bill can pass a house this session (Aug 31 of the
    second year). After it, a bill that is still in process can no longer move, and
    showing it as "in committee" would imply it can.
    """
    mt = bill["measure_type"]
    origin = "Assembly" if mt.startswith("A") else "Senate"
    second = other(origin)
    constitutional = mt in ("ACA", "SCA")
    fiscal_flag = (version or {}).get("fiscal_committee")

    ev = [(classify(h), h) for h in hist]

    # Split the history at the moment the bill reached the second house.
    arrive_x = next((i for i, (k, h) in enumerate(ev) if k == "first_read" and h["primary_location"] == second), None)
    pass_o = next((i for i, (k, h) in enumerate(ev) if k == "floor_pass" and h["primary_location"] == origin), None)
    if arrive_x is None and pass_o is not None:
        arrive_x = pass_o + 1

    def seg(lo, hi):
        return ev[lo:hi]

    o_ev = seg(0, arrive_x if arrive_x is not None else len(ev))
    x_ev = seg(arrive_x, len(ev)) if arrive_x is not None else []
    # everything after the second house's floor pass belongs to concurrence / Governor
    pass_x_i = next((i for i, (k, h) in enumerate(x_ev) if k == "floor_pass" and h["primary_location"] == second), None)
    tail = x_ev[pass_x_i + 1 :] if pass_x_i is not None else []
    if pass_x_i is not None:
        x_ev = x_ev[: pass_x_i + 1]

    vote_by_loc: dict[str, list[dict]] = {}
    for v in votes:
        vote_by_loc.setdefault(v["location_code"], []).append(v)

    def cname(code):
        return loc_names.get(code) or code

    def house_stages(house: str, events: list, key: str) -> list[dict]:
        """policy, fiscal, floor for one house."""
        cmtes, fiscal_seen, suspense, held_at = [], False, None, None
        policy_done = fiscal_done = floor_done = None
        floor_vote = None
        cur_cmte = None
        for k, h in events:
            loc3 = h["ternary_location"]
            in_cmte = h["secondary_location"] == "Committee" and loc3 and loc3.startswith(("CX", "CS"))
            if k == "cmte_pass" and cur_cmte:
                if cur_cmte in APPR:
                    fiscal_done = fiscal_done or h["action_date"]
                elif cur_cmte not in RULES:
                    policy_done = h["action_date"]
            if "senate rule 28.8" in (h["action"] or "").lower():
                fiscal_seen = True
                fiscal_done = fiscal_done or h["action_date"]
            if in_cmte:
                cur_cmte = loc3
                if loc3 in APPR:
                    fiscal_seen = True
                elif loc3 not in RULES and loc3 not in cmtes:
                    cmtes.append(loc3)
            if k == "suspense":
                suspense = suspense or h["action_date"]
                fiscal_seen = fiscal_seen or "appr" in (h["action"] or "").lower()
            if k == "held":
                held_at = h["action_date"]
            if k == "floor_pass" and h["primary_location"] == house:
                floor_done = h["action_date"]
                m = RE_VOTE.search(h["action"] or "")
                if m:
                    floor_vote = {"ayes": int(m.group(1)), "noes": int(m.group(2))}
        # once the bill left the policy committees for Approps or the floor, policy is done
        if cmtes and not policy_done:
            first_after = next((h["action_date"] for k, h in events
                                if h["secondary_location"] in ("Floor", "E&E") or (h["ternary_location"] in APPR)), None)
            if first_after and (fiscal_seen or floor_done):
                policy_done = first_after
        if fiscal_seen and not fiscal_done and floor_done:
            fiscal_done = floor_done
        # A bill can be sent back to a policy committee after it cleared Appropriations
        # (amended, re-referred). The stage dates from when the bill first cleared it; the
        # re-referral stays visible in the history.
        if policy_done and fiscal_done and policy_done > fiscal_done:
            policy_done = min((h["action_date"] for k, h in events if k == "cmte_pass" and h["action_date"] <= fiscal_done), default=fiscal_done)
        if policy_done and floor_done and policy_done > floor_done:
            policy_done = floor_done
        if fiscal_done and floor_done and fiscal_done > floor_done:
            fiscal_done = floor_done
        cvotes = []
        for c in cmtes + ([next(iter(APPR & set(vote_by_loc)))] if fiscal_seen and APPR & set(vote_by_loc) else []):
            for v in vote_by_loc.get(c, []):
                cvotes.append({"committee": cname(c), "date": v["date"], "ayes": v["ayes"], "noes": v["noes"], "result": v["result"]})
        fv = [v for v in vote_by_loc.get("AFLOOR" if house == "Assembly" else "SFLOOR", [])]
        floor_meta = floor_vote or ({"ayes": fv[0]["ayes"], "noes": fv[0]["noes"]} if (floor_done and fv) else None)
        return [
            {"key": f"policy_{key}", "kind": "policy", "house": house,
             "committees": [cname(c) for c in cmtes], "done": policy_done,
             "votes": [v for v in cvotes if v["committee"] in [cname(c) for c in cmtes]]},
            {"key": f"fiscal_{key}", "kind": "fiscal", "house": house, "done": fiscal_done,
             "applies": fiscal_seen or (fiscal_flag == "Yes" and not floor_done),
             "suspense": suspense, "held": held_at if not fiscal_done else None,
             "votes": [v for v in cvotes if v["committee"] not in [cname(c) for c in cmtes]]},
            {"key": f"floor_{key}", "kind": "floor", "house": house, "done": floor_done, "vote": floor_meta},
        ]

    intro_date = next((h["action_date"] for k, h in ev if k == "first_read"), hist[0]["action_date"] if hist else None)
    stages = [{"key": "introduced", "kind": "introduced", "house": origin, "done": intro_date}]
    stages += house_stages(origin, o_ev, "o")
    stages += house_stages(second, x_ev, "x")

    conc_pending = next((h["action_date"] for k, h in tail if k == "concur_pending"), None)
    concurred = next((h for k, h in tail if k == "concurred"), None)
    conc_vote = None
    if concurred:
        m = RE_VOTE.search(concurred["action"] or "")
        conc_vote = {"ayes": int(m.group(1)), "noes": int(m.group(2))} if m else None
    went_straight = any(k == "enrolled" for k, _ in ev) and not (conc_pending or concurred)
    stages.append({"key": "concurrence", "kind": "concurrence", "house": origin,
                   "done": concurred["action_date"] if concurred else None,
                   "applies": not went_straight, "vote": conc_vote, "pending": conc_pending})

    enrolled = next((h["action_date"] for k, h in ev if k == "enrolled"), None)
    approved = next((h["action_date"] for k, h in ev if k == "approved"), None)
    vetoed = next((h["action_date"] for k, h in ev if k == "vetoed"), None)
    chap = next((h for k, h in ev if k == "chaptered"), None)
    chapter = None
    if bill.get("chapter_num"):
        chapter = {"number": int(bill["chapter_num"]), "year": int(bill["chapter_year"])}
    elif chap:
        m = RE_CHAPTER.search(chap["action"] or "")
        if m:
            chapter = {"number": int(m.group(1)), "year": int(m.group(2))}

    if constitutional:
        stages.append({"key": "sos", "kind": "sos", "house": "Secretary of State",
                       "done": chap["action_date"] if chap else None})
        stages.append({"key": "ballot", "kind": "ballot", "house": "Voters", "done": None})
    else:
        stages.append({"key": "governor", "kind": "governor", "house": "Governor",
                       "presented": enrolled, "done": approved, "vetoed": vetoed})
        stages.append({"key": "chaptered", "kind": "chaptered", "house": "Secretary of State",
                       "done": chap["action_date"] if chap else (approved if chapter else None),
                       "chapter": chapter})

    # ---- statuses
    status_raw = bill["current_status"] or ""
    died = status_raw in ("Died", "Failed") or any(k == "died" for k, _ in ev)
    if vetoed:
        outcome = "vetoed"
    elif chapter or status_raw == "Chaptered":
        outcome = "law"
    elif approved:
        outcome = "law"
    elif enrolled:
        outcome = "governor"
    elif died:
        outcome = "died"
    elif stalled_after and today > stalled_after:
        outcome = "stalled"
    else:
        outcome = "active"

    current_i = None
    for i, s in enumerate(stages):
        applies = s.get("applies", True)
        if not applies:
            s["state"] = "skipped"
            continue
        if s["done"]:
            s["state"] = "done"
            continue
        if current_i is None:
            current_i = i
            s["state"] = "current"
        else:
            s["state"] = "upcoming"

    if outcome == "vetoed":
        for s in stages:
            if s["kind"] == "governor":
                s["state"] = "failed"; s["done"] = None; s["stoppedOn"] = vetoed; s["reason"] = "Vetoed"
            if s["kind"] == "chaptered":
                s["state"] = "upcoming"
        current_i = next(i for i, s in enumerate(stages) if s["kind"] == "governor")
    elif outcome == "law":
        for s in stages:
            if s["state"] in ("current", "upcoming") and s["kind"] not in ("chaptered",):
                # an older bill whose history skips a milestone: it did happen
                s["state"] = "skipped" if s["kind"] in ("fiscal", "concurrence") else "done"
        current_i = len(stages) - 1
        stages[-1]["state"] = "done" if stages[-1]["done"] or chapter else "current"
    elif outcome in ("died", "stalled") and current_i is not None:
        stages[current_i]["state"] = "failed" if outcome == "died" else "stalled"
        fiscal_held = stages[current_i]["kind"] == "fiscal" and stages[current_i].get("held")
        stop = next((h["action_date"] for k, h in reversed(ev) if k in ("died", "held")), None)
        stages[current_i]["stoppedOn"] = stop or (hist[-1]["action_date"] if hist else None)
        stages[current_i]["reason"] = (
            "Held on the Appropriations suspense file" if fiscal_held else
            "Died" if outcome == "died" else "Did not advance before the session deadline")

    for s in stages:
        s["label"] = STAGE_LABEL[s["kind"]]

    return {"origin": origin, "stages": stages, "outcome": outcome,
            "current": stages[current_i]["key"] if current_i is not None else None,
            "chapter": chapter, "presented": enrolled, "approved": approved, "vetoed": vetoed}
