"""Code sections a bill touches, parsed from its official title, and the practice areas
those sections belong to. Deterministic: a bill is filed under an area because of what
it amends, never because a word appears in its subject. Editorial overrides live in
editorial/notes.json (`areas`)."""
from __future__ import annotations

import re

# code title as it appears in bill titles -> leginfo lawCode
CODE_ABBR = {
    "Business and Professions Code": "BPC", "Civil Code": "CIV", "Code of Civil Procedure": "CCP",
    "Education Code": "EDC", "Elections Code": "ELEC", "Evidence Code": "EVID", "Family Code": "FAM",
    "Financial Code": "FIN", "Fish and Game Code": "FGC", "Food and Agricultural Code": "FAC",
    "Government Code": "GOV", "Harbors and Navigation Code": "HNC", "Health and Safety Code": "HSC",
    "Insurance Code": "INS", "Labor Code": "LAB", "Penal Code": "PEN", "Probate Code": "PROB",
    "Public Contract Code": "PCC", "Public Resources Code": "PRC", "Public Utilities Code": "PUC",
    "Revenue and Taxation Code": "RTC", "Streets and Highways Code": "SHC",
    "Unemployment Insurance Code": "UIC", "Vehicle Code": "VEH", "Water Code": "WAT",
    "Welfare and Institutions Code": "WIC", "Corporations Code": "CORP", "Commercial Code": "COM",
}
_CODE_RE = re.compile("(" + "|".join(sorted(map(re.escape, CODE_ABBR), key=len, reverse=True)) + ")")
_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)*)(?![\w])")
_SKIP_BEFORE = re.compile(r"(Chapter|Article|Division|Part|Title|Statutes of|Chapters|Articles|Parts)\s*$", re.I)


def code_sections(title: str) -> list[dict]:
    """[{code: 'GOV', name: 'Government Code', section: '65915', verb: 'amend'}] in order."""
    if not title:
        return []
    out, last = [], 0
    for m in _CODE_RE.finditer(title):
        chunk = title[last : m.start()]
        verb = "amend"
        for n in _NUM_RE.finditer(chunk):
            before = chunk[max(0, n.start() - 14) : n.start()]
            if _SKIP_BEFORE.search(before):
                continue
            ctx = chunk[: n.start()].lower()
            verb = ("add" if ctx.rfind(" add ") > max(ctx.rfind(" amend"), ctx.rfind(" repeal")) else
                    "repeal" if ctx.rfind(" repeal") > max(ctx.rfind(" amend"), ctx.rfind(" add ")) else "amend")
            if "and repeal" in ctx[-40:] and verb == "amend":
                verb = "amend"
            num = n.group(1)
            if float(num.split(".")[0]) < 1:
                continue
            out.append({"code": CODE_ABBR[m.group(1)], "name": m.group(1), "section": num, "verb": verb})
        last = m.end()
    seen, uniq = set(), []
    for s in out:
        k = (s["code"], s["section"])
        if k not in seen:
            seen.add(k); uniq.append(s)
    return uniq


def _sec(s: str) -> float:
    parts = s.split(".")
    return float(parts[0]) + (float("0." + parts[1].zfill(3)) if len(parts) > 1 and parts[1].isdigit() else 0)


# (area key, label, code, lo, hi). Ranges are inclusive and deliberately coarse.
AREAS = [
    ("density", "Density bonus", "GOV", "65915", "65918.99"),
    ("streamlining", "By-right and streamlined approval", "GOV", "65912.100", "65912.199"),
    ("streamlining", "By-right and streamlined approval", "GOV", "65913.4", "65913.99"),
    ("streamlining", "By-right and streamlined approval", "GOV", "65905.5", "65905.5"),
    ("haa", "Housing Accountability Act", "GOV", "65589.5", "65589.5"),
    ("element", "Housing element and RHNA", "GOV", "65580", "65589.4"),
    ("element", "Housing element and RHNA", "GOV", "65589.6", "65589.99"),
    ("adu", "ADUs and lot splits", "GOV", "65852.2", "65852.26"),
    ("adu", "ADUs and lot splits", "GOV", "66314", "66342.99"),
    ("adu", "ADUs and lot splits", "GOV", "66411.7", "66411.7"),
    ("zoning", "Zoning and land use", "GOV", "65850", "65863.99"),
    ("zoning", "Zoning and land use", "GOV", "65300", "65403.99"),
    ("permits", "Permits and timelines", "GOV", "65920", "65964.99"),
    ("fees", "Impact fees", "GOV", "66000", "66025.99"),
    ("surplus", "Surplus land", "GOV", "54220", "54234.99"),
    ("homeless", "Homelessness and shelter", "GOV", "8698", "8698.99"),
    ("homeless", "Homelessness and shelter", "WIC", "8255", "8257.99"),
    ("tenant", "Tenant protections", "CIV", "1940", "1954.99"),
    ("tenant", "Tenant protections", "CIV", "798", "799.99"),
    ("tenant", "Tenant protections", "CCP", "1159", "1179.99"),
    ("ceqa", "CEQA", "PRC", "21000", "21189.99"),
    ("taxcredit", "Tax credits and property tax", "RTC", "12206", "12206.99"),
    ("taxcredit", "Tax credits and property tax", "RTC", "17058", "17058.99"),
    ("taxcredit", "Tax credits and property tax", "RTC", "23610.5", "23610.5"),
    ("taxcredit", "Tax credits and property tax", "RTC", "214", "214.99"),
    ("taxcredit", "Tax credits and property tax", "HSC", "50199.4", "50199.22"),
    ("funding", "State housing programs", "HSC", "50000", "54000"),
    ("building", "Building standards", "HSC", "17910", "17998.99"),
    ("building", "Building standards", "HSC", "18000", "18153.99"),
    ("mobilehome", "Mobilehomes", "HSC", "18200", "18700"),
    ("redevelopment", "Redevelopment successors", "HSC", "33000", "34191.99"),
    ("cid", "Common interest developments", "CIV", "4000", "6150"),
    ("building", "Building standards", "HSC", "19960", "19997.99"),
    ("building", "Building standards", "HSC", "18900", "18949.99"),
    ("surplus", "Surplus land", "GOV", "54235", "54238.99"),
    ("coastal", "Coastal Act", "PRC", "30000", "30900"),
    ("taxcredit", "Tax credits and property tax", "RTC", "17053", "17053.99"),
    ("taxcredit", "Tax credits and property tax", "RTC", "23600", "23699.99"),
    ("finance", "Infrastructure finance districts", "GOV", "53311", "53368.99"),
    ("finance", "Infrastructure finance districts", "GOV", "53398.50", "53398.88"),
    ("authorities", "Housing authorities", "HSC", "34200", "34380"),
]
AREA_LABEL = {k: l for k, l, *_ in AREAS}

_KEYWORDS = [
    ("density", r"density bonus"), ("adu", r"accessory dwelling|junior accessory|lot split|urban lot"),
    ("ceqa", r"\bCEQA\b|California Environmental Quality Act|environmental quality"),
    ("tenant", r"tenan|eviction|rent (?:control|stabiliz|cap)|rental housing: "),
    ("homeless", r"homeless|shelter"), ("surplus", r"surplus land"),
    ("taxcredit", r"tax credit|welfare exemption|property tax"), ("fees", r"impact fee|development fee|mitigation fee"),
    ("element", r"housing element|regional housing need"), ("streamlining", r"ministerial|by right|use by right|streamlin"),
    ("mobilehome", r"mobilehome|manufactured home"), ("cid", r"common interest development"),
    ("building", r"factory-built|building standards|heat pump"), ("coastal", r"coastal"),
    ("finance", r"community facilities district|financing district"), ("permits", r"permit streamlining|post-entitlement"),
]


def areas(sections: list[dict], subject: str) -> list[str]:
    found = []
    for s in sections:
        try:
            v = _sec(s["section"])
        except ValueError:
            continue
        for key, _l, code, lo, hi in AREAS:
            if s["code"] == code and _sec(lo) <= v <= _sec(hi) and key not in found:
                found.append(key)
    if not found:
        for key, pat in _KEYWORDS:
            if re.search(pat, subject or "", re.I) and key not in found:
                found.append(key)
    return found or ["other"]


AREA_LABEL["other"] = "Other housing"
