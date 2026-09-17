# Runs INSIDE the scheduler image on the server after the deploy. Read-only
# except the dispatcher's own state file (which the cron tick writes anyway).
import json
import subprocess
import sys

sys.path.insert(0, "/app/eval")
import dispatch_policy as dp
import model_tools

print("==== dispatcher dry run on the server (real bootstrap, real season file) ====")
r = subprocess.run([sys.executable, "/app/eval/deadline_dispatcher.py", "--season", "2026-27", "--dry-run"],
                   capture_output=True, text=True)
print(r.stdout.strip(), "| exit", r.returncode)

print("\n==== state file (written by the cron tick) ====")
st = model_tools._dispatch_state()
print(json.dumps({k: st.get(k) for k in ("last_tick", "expected_next", "consecutive_nightly_failures",
                                           "last_success", "slots")}, indent=1))

print("\n==== /health ====")
h = model_tools.health()
print(json.dumps({"status": h["status"], "reasons": h["reasons"], "last_run": h["last_run"],
                  "schedule": h["data_freshness_by_source"].get("schedule")}, indent=1))

print("\n==== get_prediction carries built + next_run_expected (run 5, pre-multi-run) ====")
p = model_tools.get_prediction(411, 4)
print(json.dumps({k: p.get(k) for k in ("run_id", "kind", "slot", "built", "next_run_expected")}, indent=1))

print("\n==== frame-based tool: get_my_xi built line (no sidecar yet -> falls back to the latest run) ====")
x = model_tools.get_my_xi()
print(json.dumps({k: x.get(k) for k in ("gw", "predictions_as_of_cutoff_gw", "built", "next_run_expected")}, indent=1)
      if "error" not in x else x["error"])
