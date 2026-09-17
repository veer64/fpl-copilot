"""The loud detector on the deployed image, against the real inputs: a strict baseline build of
GW5 at horizon 6 RETURNS (no raise) with the MODEL DEGRADED findings naming the club and its
lambda; and those findings become health reasons through the same helper /health uses.
Read-only: build_deadline_frame writes nothing."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/squad"); sys.path.insert(0, "/app/eval")
import live_deadline as ld
import model_tools as mt

print("image has MODEL_DEGRADED:", ld.MODEL_DEGRADED, "| bounds", ld.LAMBDA_MIN, ld.LAMBDA_MAX)
frame, findings = ld.build_deadline_frame("2026-27", 5, strict=True, config="baseline", horizon=6)
print(f"strict build returned: {len(frame)} rows, {len(findings)} findings")
deg = [f for f in findings if f.startswith(ld.MODEL_DEGRADED)]
print(f"MODEL DEGRADED findings: {len(deg)}")
for f in deg:
    print("  ", f[:260])
print("as health reasons:")
for r in mt._model_degraded_reasons({"run_id": "next", "strict_findings": {"baseline": findings}}):
    print("  ", r[:200])
lam = frame[frame["gw"] == 6].groupby("team")["team_lambda"].first()
print("check against the known lambda: Coventry City GW6 =", round(float(lam.get("Coventry City", float('nan'))), 4))
