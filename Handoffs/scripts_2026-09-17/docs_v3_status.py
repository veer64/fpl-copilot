from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\Logs\dc_shrinkage_v3_prereg_2026-09-17.md")
s = p.read_text(encoding="utf-8")
old = "# Pre-registration v3: a PROMOTED-CLUB CENTRE for the hinge prior (2026-09-17 evening) — DESIGN ONLY, not implemented\n"
new = ("# Pre-registration v3: a PROMOTED-CLUB CENTRE for the hinge prior (2026-09-17 evening)\n\n"
       "> **STATUS 2026-09-17 19:00Z: IMPLEMENTED on branch `hinge-box-v2` (commit adddc17, unpushed), the endpoint RUN, verdict\n"
       "> MARGINAL by §4's rule (pooled top-30 −1.35 SE), NOT ADOPTED.** Execution log: `Logs/dc_shrinkage_v3_log_2026-09-17.md`.\n"
       "> The centre was not the lever: every sensitivity centre is marginal by the same clause, 2025-26's luck component being\n"
       "> the residual. Nothing below is amended.\n")
assert old in s
p.write_text(s.replace(old, new), encoding="utf-8")

p = Path(r"C:\dev\fpl-copilot\KNOWN_ISSUES.md")
s = p.read_text(encoding="utf-8", newline="")
nl = "\r\n" if "\r\n" in s else "\n"
old = "falsified / MARGINAL / pass defined before any number; not implemented."
assert old in s
add = ("**2026-09-17 19:00Z:** v3 implemented on the branch and run: starters +0.0018 (+2.1 SE), top-30 -0.0075 (-1.35 SE),\n"
       "every structural gate held, verdict MARGINAL by the pre-fixed rule -> NOT adopted. The residual is 2025-26's\n"
       "luck component (the record's Sunderland runaway paid off), present at every centre tried; the centre is not\n"
       "the lever. Per the prereg: no fourth form without a new argument; let Coventry score. The loud detector\n"
       "remains the live floor. STILL OPEN.")
p.write_text(s.replace(old, old + nl + add.replace("\n", nl)), encoding="utf-8", newline="")

Path(r"C:\Users\veers\AppData\Local\Temp\claude\c--dev-fpl-copilot\574ea3ed-213b-423b-b29f-4574a15eca54\scratchpad\commit_msg_v3.txt").write_text(
    "log: prereg v3 (promoted-club centre) implemented on branch hinge-box-v2 and run against its pre-fixed rule -- "
    "starters +0.0018 (+2.1 SE), top-30 -0.0075 (-1.35 SE), every structural gate held, verdict MARGINAL, NOT adopted; "
    "the centre did what it was built to do (promoted clubs' early lambda down a quarter, fewer of their players in the "
    "top 30) and every sensitivity centre is marginal by the same clause -- the residual is 2025-26's luck component; "
    "the Luton reading was not borne out; no fourth form; let Coventry score\n\n"
    "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>\n", encoding="utf-8")
print("prereg status + known issues updated; commit message written")
