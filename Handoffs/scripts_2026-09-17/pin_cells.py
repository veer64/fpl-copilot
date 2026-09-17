"""Read the gap0-family cells from the rebuilt armlogs with the index builder's OWN read
layer (eval/build_season_totals_index.rows_arms), with its drift asserts made vacuous and
the __PIN__ placeholders stubbed, and print the cells to pin. Read-only."""
import io
import re
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(r"C:\dev\fpl-copilot")
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
src = (REPO / "eval" / "build_season_totals_index.py").read_text(encoding="utf-8")
src = src.replace("__PIN_GAP0__", "(0, 0, 0)").replace("__PIN_HMIN__", "(0, 0, 0)").replace("__PIN_BOTH__", "(0, 0)")
# make the two drift asserts vacuous (read layer only; the real module keeps them)
src = re.sub(r"^(\s+)assert got\[k\] == v, .*$", r"\1pass", src, flags=re.M)
src = re.sub(r"^(\s+)assert ref == EXPECT_REFERENCE_CHIP, .*$", r"\1pass", src, flags=re.M)
mod = types.ModuleType("bsti_stub")
mod.__file__ = str(REPO / "eval" / "build_season_totals_index.py")
exec(compile(src, mod.__file__, "exec"), mod.__dict__)
buf = io.StringIO()
with redirect_stdout(buf):
    rows = mod.rows_arms()
want = re.compile(r"^(gap0_tc2|hmin_gap0(_tc2)?|both_gap0(_tc2)?)(_pre_dcfix|_preasof)?$")
out = []
for r in rows:
    arm = r["source"].split("armlog_")[-1].replace(".parquet", "")
    arm = re.sub(r"^\d{4}_\d{2}_", "", arm)
    if want.match(arm):
        out.append((r["season"], arm, r["chip"], r["path"], r["source"]))
for s, a, chip, pt, path in sorted(out):
    print(f"{s}  {a:28s}  chip-incl {chip}  path {pt}   {path}")
print("\nkeys of a row:", sorted(rows[0].keys()))
