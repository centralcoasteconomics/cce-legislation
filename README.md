# cce-legislation

Data behind the **Legislative Log** and **Housing Laws** pages on centralcoasteconomics.com.

Every night a GitHub Action reads the Legislative Counsel of California's official bulk
archive (`downloads.leginfo.legislature.ca.gov/pubinfo_<year>.zip`, ~1.3 GB), fetching only
the tables and bill texts it needs with HTTP range requests (~22 MB), and writes:

| File | What |
|---|---|
| `data/index.json` | one row per housing bill: status, stage, authors, practice areas |
| `data/bills/<slug>.json` | the full record: trackline stages, history, votes, digest, analyses, veto message, links |
| `data/changes.json` | what moved since the previous run (the steward's morning pass reads this) |
| `data/meta.json` | source, freshness, counts, the session calendar |

**Housing bill** = referred to the Assembly Housing and Community Development Committee
(`CX10`) or the Senate Housing Committee (`CS75`), plus hand additions in
`editorial/include.json`. The website fetches these files from this public repository at
request time, so a status change goes live without a site deploy.

`editorial/` holds the only human-written text (watch list, notes, ballot measures). It is
neutral: what a bill does and why practitioners track it, never a position.

```bash
python3 pipeline/build.py --cache .cache   # dev: keeps fetched members between runs
python3 tests/test_invariants.py           # every trackline must be consistent
python3 tests/verify_editorial.py          # the editorial gate (neutral, no dashes, Rule #0)
```
