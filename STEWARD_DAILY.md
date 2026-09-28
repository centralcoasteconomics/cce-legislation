# Legislative Log: the steward's morning pass

Daily, around 7:00 Pacific, after the nightly Action has rebuilt `data/` from the
Legislative Counsel's archive. Part of the CCE platform steward's duties (Ryan, 2026-09-28).
CCE is Ryan's personal venture: nothing here may name or touch Many Mansions (Rule #0).

The data refresh is fully automatic; this pass exists only for the words a machine should
not write: the **Legislation to Watch** list and the **Why practitioners track it** notes.
Most mornings nothing moved, and the pass should take a minute.

## Steps

1. `cd ~/Developer/cce-legislation && git pull --ff-only`
2. **Did the nightly run?** `gh run list --workflow nightly-legislative-log --limit 1`.
   A red run means the site is serving yesterday's data (the stale copy keeps it up).
   Re-run once (`gh workflow run nightly-legislative-log`) before diagnosing: the
   Legislature's server drops connections under load. Two failures in a row is a real
   defect; report it and stop.
3. **Read `data/changes.json`.** Empty, or only `lastAction` date changes with no new
   outcome or stage: log "no movement" and stop. Otherwise, for each change:
   - `governor -> law` or `governor -> vetoed`: if the bill is on the watch list, retire it.
     Its page already says what happened; the Housing Laws tab picks up new law by itself.
   - a new bill (from December, the 2027-28 session): if it amends a core practice area
     (density bonus, streamlining, HAA, CEQA, tax credits, housing element), consider a note.
   - a bill reaching a floor vote, the Governor, or a suspense-file hearing: consider
     promoting it to the watch list.
4. **Write only from the record.** A note or `why` is one to three sentences, drawn from the
   Legislative Counsel's Digest in `data/bills/<slug>.json`, in the conditional ("Would
   require..."). What it changes for a practitioner; never whether it should pass. No em or
   en dashes. Keep the watch list at six or fewer, each tied to a live bill.
5. **Gate.** `python3 tests/verify_editorial.py` must print OK. Fix, never bypass.
6. **Publish.** `git add editorial && git commit -m "editorial: <date> <what>" && git push`.
   The site reads the repo; no deploy is needed. Confirm from the edge within 15 minutes:
   `curl -s https://centralcoasteconomics.com/legislation | grep -c 'class="wcard'`.
7. **One line to the steward log** (`~/Developer/CCE_PRIMER.md` §7c): date, changes seen,
   editorial edits made.

## Seasonal

- **By Sept 30 (even years):** every bill at the Governor resolves. Retire the whole
  "On the Governor's desk" list; retitle it for the season ("New law, effective January 1").
- **Nov 3, 2026:** add `result` to each measure in `editorial/ballot.json` from the
  Secretary of State's semi-official results with `asOf`, then again at certification.
- **Early December:** the 2027-28 session convenes (Dec 7, 2026). The archive becomes
  `pubinfo_2027.zip`; add the session to `config/session.json` (keep 2025 for Housing
  Laws) and transcribe the 2027 legislative calendar once the Legislature adopts it.
