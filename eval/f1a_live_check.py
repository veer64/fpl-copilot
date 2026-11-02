"""Prompt F1a Part 6 (2026-11-02): the live laptop check of the website backend -- not pytest.

The app in process (TestClient, lifespan run) in AUTH_MODE=clerk on the laptop database `fpl`, the real agent (graph engine,
Anthropic), the real FPL API (fpl_import: >= 1 s between requests, every request ledgered), Langfuse off.

1. A REAL Clerk dev session token (Backend API: a throwaway user, a session, a token; the user deleted at the end) carries
   no azp, so the app refuses it now: 401 is the expected answer.
2. Every other call carries a token signed here with a local RSA key (CLERK_JWT_KEY = its public PEM, CLERK_ISSUER a local
   issuer, azp = the website's origin) -- the pytest fixtures' way, in process; never a server flag. The two test users'
   Clerk profiles are faked (example.test emails), so they are new app_users rows (ids from 10001 up).
3. Three real team ids from page 1 of FPL's overall league (leagues-classic/314/standings/, read from the file saved at
   20:08Z, no new request): all three imported for user A, the first for user B, the first refreshed (a new version).
4. At most six agent turns: A "Who is my captain?" (team 1), team 2 activated, the same question (team 2), "Make <team 2's
   vice-captain> my captain." (a preview: ticket issued y/n), team 3 activated, "Yes, do it." (nothing written); B "Who is
   my captain?" (B's team). B cannot see A's thread or teams (403 / 404, no model call).

Writes (laptop only): two app_users rows (>= 10001), their user_fpl_teams rows, squad_versions rows under the teams' keys
(append-only, listed), threads / checkpoints / chat_usage / squad_previews rows of those two users.

Usage: python eval/f1a_live_check.py [--out DIR]   -> <DIR>/p6_live.json + a printed summary."""
import argparse
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")
ORIGIN = "http://localhost:3000"
os.environ.update(AUTH_MODE="clerk", LANGFUSE_ENABLED="0", CLERK_AUTHORIZED_PARTIES=ORIGIN)
for k in ("FPL_USER_ID", "AGENT_ENGINE", "CORS_ALLOWED_ORIGINS", "CLERK_JWT_KEY", "CLERK_ISSUER"):
    os.environ.pop(k, None)

import requests  # noqa: E402

CLERK_API = "https://api.clerk.com/v1"
FPL_CAP = 40
ANTHROPIC_CAP_USD = 1.50
MAX_TURNS = 6


def mask_id(x):
    return f"***{str(x)[-3:]}"


class Run:
    def __init__(self, out_dir):
        self.out_dir = Path(out_dir)
        self.out = {"started": datetime.now(timezone.utc).isoformat(), "steps": [], "imports": [], "turns": [],
                    "clerk_users_created": 0, "clerk_users_deleted": 0}

    def step(self, name, ok, **info):
        self.out["steps"].append({"name": name, "ok": bool(ok), **info})
        print(f"{name}: {'PASS' if ok else 'FAIL'} {json.dumps(info, default=str)[:600]}", flush=True)

    def save(self):
        (self.out_dir / "p6_live.json").write_text(json.dumps(self.out, indent=1, default=str), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\dev\fpl-backups\f1a_backend_files")
    args = ap.parse_args()
    run = Run(args.out)
    ledger = Path(args.out) / "fpl_requests.log"
    standings = json.loads((Path(args.out) / "fpl_raw" / "standings_314_p1.json").read_text(encoding="utf-8"))
    candidates = [int(r["entry"]) for r in standings["standings"]["results"]]
    run.out["standings_ids_first6"] = candidates[:6]
    print("team ids (standings page 1, first 6):", [mask_id(x) for x in candidates[:6]], flush=True)

    import agent
    import db_write
    import fpl_import
    import main as app_main
    import squad_store
    import users
    from fastapi.testclient import TestClient

    # the FPL ledger: every request, its status, >= 1 s apart (fpl_import spaces them)
    real_get = fpl_import._http_get

    def ledgered(url):
        if sum(1 for _ in ledger.open(encoding="utf-8")) >= FPL_CAP:
            raise fpl_import.FplUnavailable("the prompt's FPL cap (40 requests) is reached")
        status, body = real_get(url)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {status} {url.split('/api/', 1)[1]}\n")
        return status, body
    fpl_import._http_get = ledgered
    raws = {}
    real_fetch = fpl_import.fetch_team

    def keep(fpl_team_id, now=None, get=None):
        raw = real_fetch(fpl_team_id, now=now, get=get)
        raws[int(fpl_team_id)] = raw
        return raw
    fpl_import.fetch_team = keep

    calls = []
    real_create = agent.client.messages.create

    def counted(**kw):
        calls.append(1)
        return real_create(**kw)
    agent.client.messages.create = counted
    squad_calls = []
    for name in ("set_my_squad", "get_my_squad"):
        real_tool = agent.available_functions[name]

        def wrapped(_real=real_tool, _name=name, **kw):
            res = _real(**kw)
            squad_calls.append({"tool": _name, "input": kw, "result_keys": sorted(res) if isinstance(res, dict) else None,
                                "refused": res.get("refused") if isinstance(res, dict) else None,
                                "reason": res.get("reason") if isinstance(res, dict) else None,
                                "committed": res.get("committed") if isinstance(res, dict) else None,
                                "ticket": res.get("preview_ticket") if isinstance(res, dict) else None})
            return res
        agent.available_functions[name] = wrapped

    conn = db_write.connect()
    conn.autocommit = True

    def q(sql, params=()):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description is not None else []

    users.ensure_schema()
    max_version_before = q("SELECT COALESCE(max(version_id), 0) FROM squad_versions")[0][0]
    max_usage_before = q("SELECT COALESCE(max(id), 0) FROM chat_usage")[0][0]
    run.out["squad_versions_max_before"] = max_version_before

    clerk_created = []
    H = {"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY'].strip()}", "Content-Type": "application/json"}
    with TestClient(app_main.app) as client:
        # ---- 1. a real Clerk dev token: no azp -> 401 ------------------------------------------------------------------
        try:
            body = {"email_address": [f"f1alive{secrets.token_hex(3)}+clerk_test@example.com"],
                    "password": secrets.token_urlsafe(18), "first_name": "F1a", "last_name": "Live"}
            r = requests.post(f"{CLERK_API}/users", headers=H, json=body, timeout=20)
            r.raise_for_status()
            cid = r.json()["id"]
            clerk_created.append(cid)
            run.out["clerk_users_created"] += 1
            s = requests.post(f"{CLERK_API}/sessions", headers=H, json={"user_id": cid}, timeout=20)
            s.raise_for_status()
            t = requests.post(f"{CLERK_API}/sessions/{s.json()['id']}/tokens", headers=H, json={"expires_in_seconds": 120},
                              timeout=20)
            t.raise_for_status()
            import jwt
            claims = jwt.decode(t.json()["jwt"], options={"verify_signature": False})
            before = q("SELECT count(*) FROM app_users")[0][0]
            r = client.get("/me", headers={"Authorization": f"Bearer {t.json()['jwt']}"})
            run.step("1 real Clerk dev token (no azp) is refused", r.status_code == 401 and "azp" not in claims
                     and q("SELECT count(*) FROM app_users")[0][0] == before,
                     http=r.status_code, token_has_azp="azp" in claims, claims=sorted(claims))
        finally:
            for cid in clerk_created:
                try:
                    d = requests.delete(f"{CLERK_API}/users/{cid}", headers=H, timeout=20)
                    run.out["clerk_users_deleted"] += int(d.ok and d.json().get("deleted") is True)
                except Exception as e:  # noqa: BLE001
                    print(f"clerk delete failed: {type(e).__name__}", flush=True)

        # ---- 2. local signing from here on --------------------------------------------------------------------------
        import auth
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        os.environ["CLERK_JWT_KEY"] = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        os.environ["CLERK_ISSUER"] = "https://f1a-live-check.local"
        auth._reset()
        tag = secrets.token_hex(3)
        subs = {"A": f"user_f1a_live_a_{tag}", "B": f"user_f1a_live_b_{tag}"}
        profiles = {subs["A"]: {"email": f"f1a.a.{tag}@example.test", "email_verified": True, "name": "F1a Live A",
                                "sign_in_method": "email"},
                    subs["B"]: {"email": f"f1a.b.{tag}@example.test", "email_verified": True, "name": "F1a Live B",
                                "sign_in_method": "email"}}
        users.fetch_profile = lambda clerk_user_id: dict(profiles[clerk_user_id])

        def h(who):
            now = int(time.time())
            tok = jwt.encode({"sub": subs[who], "sid": f"sess_{who}", "iss": os.environ["CLERK_ISSUER"], "iat": now,
                              "nbf": now - 2, "exp": now + 60, "azp": ORIGIN, "v": 2}, private, algorithm="RS256",
                             headers={"kid": "f1a_live"})
            return {"Authorization": f"Bearer {tok}"}

        me_a, me_b = client.get("/me", headers=h("A")).json(), client.get("/me", headers=h("B")).json()
        ua, ub = me_a["user_id"], me_b["user_id"]
        run.out["users"] = {"A": ua, "B": ub}
        run.step("2 local tokens sign in two new test users", ua >= 10001 and ub >= 10001 and ua != ub, A=ua, B=ub)

        # ---- 3. imports -----------------------------------------------------------------------------------------------
        def do_import(who, fid, label):
            for attempt in (1, 2):
                r = client.post("/me/teams", json={"fpl_team_id": fid, "label": label}, headers=h(who))
                if r.status_code != 503 or attempt == 2:
                    return r
                print("FPL 503: waiting 60 s once", flush=True)
                time.sleep(60)

        chosen, spare = [], list(candidates)
        for k in range(3):
            while spare:
                fid = spare.pop(0)
                r = do_import("A", fid, f"A{k + 1}")
                if r.status_code == 200:
                    chosen.append((fid, r.json()))
                    break
                run.step(f"3 import for A of {mask_id(fid)} skipped", False, http=r.status_code, detail=r.json())
        run.out["chosen_ids"] = [fid for fid, _ in chosen]
        rb = do_import("B", chosen[0][0], "B1")
        imports = [("A", fid, body) for fid, body in chosen] + [("B", chosen[0][0], rb.json())]
        for who, fid, body in imports:
            vid = body.get("version_id")
            (doc,), = q("SELECT squad_json FROM squad_versions WHERE version_id = %s", (vid,)) or [(None,)]
            raw = raws.get(fid) or {}
            legal, err = True, None
            try:
                squad_store.validate_document(doc)
                state = squad_store.to_state(doc)
            except Exception as e:  # noqa: BLE001
                legal, err, state = False, str(e)[:300], None
            fpl_bank = (raw.get("picks", {}).get(raw.get("picks_gw"), {}).get("entry_history") or {}).get("bank")
            fpl_value = (raw.get("picks", {}).get(raw.get("picks_gw"), {}).get("entry_history") or {}).get("value")
            prices = {r[0]: r[1] for r in q("SELECT element, price_tenths FROM players_live WHERE element = ANY(%s)",
                                            ([p["element"] for p in doc["players"]],))} if doc else {}
            rec = {"who": who, "team": mask_id(fid), "version_id": vid, "picks_gw": body.get("picks_gw"),
                   "players": len(doc["players"]) if doc else None, "legal": legal, "error": err,
                   "bank": doc.get("bank") if doc else None, "fpl_bank": fpl_bank,
                   "bank_exact": bool(doc) and doc.get("bank") == fpl_bank, "free_transfers": doc.get("free_transfers") if doc else None,
                   "estimated": (doc or {}).get("provenance", {}).get("estimated"), "notes": (doc or {}).get("provenance", {}).get("notes"),
                   "diag_sell_value_plus_bank_vs_fpl_value": [state.sell_value(prices) + doc["bank"] if state else None, fpl_value]}
            run.out["imports"].append(rec)
            run.step(f"3 import {who} {mask_id(fid)}", legal and rec["players"] == 15 and rec["bank_exact"],
                     **{k: rec[k] for k in ("picks_gw", "players", "bank", "fpl_bank", "free_transfers", "estimated")})
        rr = client.post(f"/me/teams/{chosen[0][0]}/refresh", headers=h("A"))
        ok = rr.status_code == 200 and rr.json().get("supersedes") == chosen[0][1]["version_id"]
        run.step("3 refresh A team 1 writes a new version", ok, http=rr.status_code,
                 version_id=rr.json().get("version_id"), supersedes=rr.json().get("supersedes"))

        # ---- 4. agent turns ------------------------------------------------------------------------------------------
        def names_of(fid):
            key = q("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s", (ua, fid))[0][0]
            (doc,), = q("SELECT squad_json FROM squad_versions WHERE user_id = %s AND is_active", (key,))
            by_role = {p["role"]: p for p in doc["players"] if p["role"] in ("CAPTAIN", "VICE")}
            return key, by_role["CAPTAIN"]["name"], by_role["VICE"]["name"]

        def spent():
            return float(q("SELECT COALESCE(sum(usd), 0) FROM chat_usage WHERE id > %s AND user_id IN (%s, %s)",
                           (max_usage_before, ua, ub))[0][0])

        def turn(who, message, thread_id=None, check=None, label=""):
            if len(run.out["turns"]) >= MAX_TURNS or spent() >= ANTHROPIC_CAP_USD:
                run.out["turns"].append({"label": label, "status": "NOT RUN (cap)"})
                return None
            n0, c0, s0 = len(calls), spent(), len(squad_calls)
            t0 = time.time()
            body = {"message": message}
            if thread_id:
                body["thread_id"] = thread_id
            r = client.post("/chat", json=body, headers=h(who))
            ans = r.json().get("answer") if r.status_code == 200 else None
            rec = {"label": label, "who": who, "question": message, "http": r.status_code, "model_calls": len(calls) - n0,
                   "usd": round(spent() - c0, 6), "seconds": round(time.time() - t0, 1), "answer": ans,
                   "thread_id": r.json().get("thread_id") if r.status_code == 200 else None,
                   "squad_tools": squad_calls[s0:]}
            rec["result"] = check(rec) if check else None
            run.out["turns"].append(rec)
            print(f"turn {label}: http {r.status_code}, {rec['model_calls']} calls, ${rec['usd']}, result {rec['result']}; "
                  f"answer: {ascii((ans or '')[:240])}", flush=True)
            return rec

        def mentions(name):
            last = name.split()[-1].lower()
            return lambda rec: "PASS" if rec["answer"] and (name.lower() in rec["answer"].lower() or last in rec["answer"].lower()) else "FAIL"

        t1, t2, t3 = (fid for fid, _ in chosen)
        k1, cap1, _ = names_of(t1)
        r1 = turn("A", "Who is my captain?", check=mentions(cap1), label="T1 A captain (team 1)")
        thread_a = r1["thread_id"] if r1 else None
        act = client.post(f"/me/teams/{t2}/activate", headers=h("A"))
        run.step("4 activate team 2", act.status_code == 200 and act.json().get("is_active") is True, http=act.status_code)
        k2, cap2, vice2 = names_of(t2)
        turn("A", "Who is my captain?", thread_a, check=mentions(cap2), label="T2 A captain (team 2)")
        tickets_before = q("SELECT count(*) FROM squad_previews WHERE user_id = %s", (ua,))[0][0]
        v2_before = q("SELECT count(*) FROM squad_versions WHERE user_id = %s", (k2,))[0][0]
        r3 = turn("A", f"Make {vice2} my captain.", thread_a, label="T3 A preview on team 2")
        tickets_after = q("SELECT count(*) FROM squad_previews WHERE user_id = %s", (ua,))[0][0]
        ticket_issued = tickets_after > tickets_before
        run.out["ticket_issued"] = ticket_issued
        act3 = client.post(f"/me/teams/{t3}/activate", headers=h("A"))
        run.step("4 activate team 3", act3.status_code == 200 and act3.json().get("is_active") is True, http=act3.status_code)
        k3 = names_of(t3)[0]
        v3_before = q("SELECT count(*) FROM squad_versions WHERE user_id = %s", (k3,))[0][0]
        r4 = turn("A", "Yes, do it.", thread_a, label="T4 A yes after the switch")
        v2_after = q("SELECT count(*) FROM squad_versions WHERE user_id = %s", (k2,))[0][0]
        v3_after = q("SELECT count(*) FROM squad_versions WHERE user_id = %s", (k3,))[0][0]
        used = q("SELECT count(*) FROM squad_previews WHERE user_id = %s AND used_at IS NOT NULL", (ua,))[0][0]
        run.step("4 preview, team switch, yes -> no write", (v2_after, v3_after) == (v2_before, v3_before) and used == 0,
                 ticket_issued=ticket_issued, team2_versions=[v2_before, v2_after], team3_versions=[v3_before, v3_after],
                 tickets_used=used, t3_tools=r3["squad_tools"] if r3 else None, t4_tools=r4["squad_tools"] if r4 else None)
        kb = q("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s", (ub,))[0][0]
        (docb,), = q("SELECT squad_json FROM squad_versions WHERE user_id = %s AND is_active", (kb,))
        capb = next(p["name"] for p in docb["players"] if p["role"] == "CAPTAIN")
        turn("B", "Who is my captain?", check=mentions(capb), label="T5 B captain (B's team)")

        # ---- B cannot see A's thread or teams -------------------------------------------------------------------------
        n0 = len(calls)
        before = q("SELECT (SELECT count(*) FROM squad_versions), (SELECT count(*) FROM chat_threads), "
                   "(SELECT count(*) FROM user_fpl_teams), (SELECT count(*) FROM squad_previews)")[0]
        checks = {
            "B reads A's thread messages": client.get(f"/threads/{thread_a}/messages", headers=h("B")).status_code,
            "B chats in A's thread": client.post("/chat", json={"message": "hello", "thread_id": thread_a}, headers=h("B")).status_code,
            "B activates A's team 2": client.post(f"/me/teams/{t2}/activate", headers=h("B")).status_code,
            "B refreshes A's team 3": client.post(f"/me/teams/{t3}/refresh", headers=h("B")).status_code,
        }
        b_threads = [x["thread_id"] for x in client.get("/threads", headers=h("B")).json()]
        b_teams = [x["fpl_team_id"] for x in client.get("/me/teams", headers=h("B")).json()]
        after = q("SELECT (SELECT count(*) FROM squad_versions), (SELECT count(*) FROM chat_threads), "
                  "(SELECT count(*) FROM user_fpl_teams), (SELECT count(*) FROM squad_previews)")[0]
        run.step("4 B cannot see A's thread or teams",
                 checks == {"B reads A's thread messages": 403, "B chats in A's thread": 403, "B activates A's team 2": 404,
                            "B refreshes A's team 3": 404} and thread_a not in b_threads and b_teams == [t1]
                 and len(calls) == n0 and before == after,
                 codes=checks, model_calls=len(calls) - n0, rows_before=before, rows_after=after)
        msgs = client.get(f"/threads/{thread_a}/messages", headers=h("A")).json()
        delivered = [t["answer"] for t in run.out["turns"] if t.get("who") == "A" and t.get("answer")]
        run.step("4 A's thread lists the delivered answers", [m["text"] for m in msgs if m["role"] == "assistant"] == delivered,
                 messages=len(msgs))

    written = q("SELECT count(*), min(version_id), max(version_id) FROM squad_versions WHERE version_id > %s",
                (max_version_before,))[0]
    run.out["squad_versions_written"] = {"count": written[0], "first": written[1], "last": written[2]}
    run.out["usd_anthropic"] = round(spent(), 6)
    run.out["model_calls"] = len(calls)
    run.out["fpl_requests_total"] = sum(1 for _ in ledger.open(encoding="utf-8"))
    run.out["finished"] = datetime.now(timezone.utc).isoformat()
    run.save()
    print(json.dumps({k: run.out[k] for k in ("squad_versions_written", "usd_anthropic", "model_calls", "fpl_requests_total",
                                               "clerk_users_created", "clerk_users_deleted", "ticket_issued")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
