import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = "http://68.183.131.154:8000"
case, path = sys.argv[1], sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else "BEFORE"
urllib.request.urlopen(urllib.request.Request(base + "/reset", method="POST"), timeout=30).read()
body = open(path, "rb").read()
req = urllib.request.Request(base + "/chat", data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
raw = urllib.request.urlopen(req, timeout=300).read().decode("utf-8", errors="replace")
ans = json.loads(raw).get("answer", raw)
print(f"=================== {label}: {case}\n{ans}\n")
