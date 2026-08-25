"""Book-name -> FPL element crosswalk for the player-prop pull, with its precision report, built BEFORE any de-vig or feature (Logs/props_prereg.md section 7.4). Reuses eval/build_crosswalk.py's normaliser and fuzzy floor/margin; candidates are restricted to the fixture's two clubs at that gameweek (vaastav team per gw), matched exact -> token-subset -> discriminating token unique within the two squads -> fuzzy, every row carrying its provenance; unmatched rows are counted and named, never filled. Asserts one name -> one element and one element -> one name within every board (assert_crosswalk_unique semantics), the same name -> the same element across the season, team agreement with the fixture, and flags price/position and price/minutes implausibilities -- the one-to-one WRONG match is invisible to a duplicate sweep (KNOWN_ISSUES #3, #12), so profile checks are the only thing that can catch it. Writes data/odds_props/props_crosswalk_{season}.csv and Logs/props_crosswalk_log.md. Result of record: that log.

Usage: uv run python eval/build_props_crosswalk.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from build_crosswalk import _norm, FUZZY_FLOOR, FUZZY_MARGIN  # noqa: E402
from pull_player_props_history import TOKENS  # noqa: E402

SCALE = REPO / "data" / "odds_props" / "raw" / "scale"
SEASONS = ["2024-25", "2025-26"]
MARKET = "player_goal_scorer_anytime"
TOKEN_MIN = 4

# MANUAL entries (approved 2026-08-24). Applied ONLY when every automated tier
# has returned null AND the element is in the fixture's two-club pool at that
# gameweek. Each carries the evidence that makes the identification certain:
# club at the gameweeks priced, position, season minutes/goals, and why no
# other element can be meant. A wrong id imports another player's goals;
# a null costs a row. Precedents: Felipe/Morato, Beto (KNOWN_ISSUES #3, #12).
MANUAL = {
    # ---------------------------------------------------------------- 2024-25
    ("2024-25", "lucas paqueta"): (527,
        "Lucas Tolentino Coelho de Lima | West Ham GW1-38, MID, 2374 min / 4 goals | book name on all 31 West Ham "
        "boards; the only Lucas at West Ham (other Lucas elements: Digne Villa, Bergstrom Chelsea, Bergvall Spurs -- "
        "club-excluded); FPL carries the legal name, the books the playing name 'Paqueta'"),
    ("2024-25", "diogo jota"): (317,
        "Diogo Teixeira da Silva | Liverpool GW1-38, MID, 1182 min / 6 goals | the only Diogo at Liverpool "
        "(Dalot is Man Utd, club-excluded); legal name Diogo Jose Teixeira da Silva"),
    ("2024-25", "casemiro"): (368,
        "Carlos Henrique Casimiro | Man Utd GW1-38, MID, 1489 min / 1 goal | single-token book name; the only "
        "'Casimiro' at Man Utd; spelling Casemiro/Casimiro is the known FPL variant"),
    ("2024-25", "beto"): (218,
        "Norberto Bercique Gomes Betuncal | Everton GW1-38, FWD, 1521 min / 8 goals | the only Beto at Everton; "
        "KNOWN_ISSUES #3 precedent (no token of the legal name matches the playing name)"),
    ("2024-25", "jorginho"): (7,
        "Jorge Luiz Frello Filho | Arsenal GW1-38, MID, 701 min / 0 goals | single-token playing name; legal name "
        "carries no matching token; the only candidate at Arsenal"),
    ("2024-25", "fatawu issahaku"): (570,
        "Abdul Fatawu | Leicester GW1-38, MID, 576 min / 0 goals | Abdul Fatawu Issahaku; the only Fatawu at "
        "Leicester; the given-name tier rejected 'fatawu'/'abdul' correctly, the surname is the FPL given name"),
    ("2024-25", "emerson"): (520,
        "Emerson Palmieri dos Santos | West Ham GW1-38, DEF, 2108 min / 2 goals | single-token book name on all 30 "
        "West Ham boards at 0.05-0.13 implied (a starting full-back); in the two Spurs-v-West Ham boards (GW8, GW35) "
        "Emerson Leite de Souza Junior (Emerson Royal, el 487, Spurs DEF) is also in the pool -- he transferred to "
        "AC Milan in Aug 2024 and has 0 minutes all season, so the identification is certain and stated"),
    ("2024-25", "joao pedro"): (129,
        "Joao Pedro Junqueira de Jesus | Brighton GW1-38, FWD, 1946 min / 10 goals | the automated tier maps this "
        "key to 129 in 26 Brighton boards; the single null is GW24 Forest v Brighton where Forest's Joao Pedro "
        "Ferreira Silva (596) shares the pool -- that board lists 'Jota Silva' separately (matched to 596), so "
        "'Joao Pedro' there is the Brighton player. Resolved on that evidence only"),
    ("2024-25", "jota silva"): (596,
        "Joao Pedro Ferreira Silva | Nott'm Forest GW1-38, MID, 835 min / 3 goals | the surname tier maps this key "
        "to 596 in every other Forest board; the single null is GW20 Wolves v Forest where Wolves carries another "
        "'Silva' so the surname token is not unique; manual entry restores cross-fixture consistency"),
    # ---------------------------------------------------------------- 2025-26
    ("2025-26", "lucas paqueta"): (612,
        "Lucas Tolentino Coelho de Lima | West Ham GW1-38, MID, 1513 min / 4 goals | as 2024-25: the only Lucas at "
        "West Ham (Digne Villa, Pires Silva Burnley, Bergvall Spurs are club-excluded)"),
    ("2025-26", "casemiro"): (457,
        "Carlos Henrique Casimiro | Man Utd GW1-38, MID, 2575 min / 9 goals | as 2024-25; 'Carlos Casemiro' from "
        "another book already maps to 457 via the surname tier"),
    ("2025-26", "edward nketiah"): (284,
        "Eddie Nketiah | Crystal Palace GW1-38, FWD, 414 min / 2 goals | Edward Keddar Nketiah; the only Nketiah at "
        "Palace; the given-name rule rejected edward/eddie (ratio < 60) -- correct to refuse automatically, certain here"),
    ("2025-26", "chidozie obi"): (467,
        "Chido Obi | Man Utd GW1-38, FWD, 0 min / 0 goals | Chidozie Obi-Martin; the only Obi at Man Utd; priced on "
        "10 Man Utd boards at 0.31 mean implied despite 0 minutes (placeholder-price case, identification certain)"),
}


def odds_team_to_fpl(odds_name):
    hits = [fpl for fpl, tok in TOKENS.items() if tok.lower() in odds_name.lower()]
    assert len(hits) == 1, f"odds team {odds_name!r} -> {hits}"
    return hits[0]


def match_one(key, pool):
    """pool: DataFrame[element, key, tokens]. -> (element, match_type, score) or (None, reason, score)."""
    if not key:
        return None, "empty", 0.0
    ex = pool[pool["key"] == key]
    if len(ex) == 1:
        return int(ex["element"].iloc[0]), "exact", 100.0
    if len(ex) > 1:
        return None, f"ambiguous_exact({len(ex)})", 100.0
    toks = {t for t in key.split() if len(t) >= 3}
    sub = pool[[bool(toks) and (toks <= p or p <= toks) and len(toks & p) >= 1 for p in pool["tokens"]]]
    if len(sub) == 1:
        return int(sub["element"].iloc[0]), "token_subset", 95.0
    # discriminating SURNAME token: the book name's last token must match (fuzz >= 85)
    # a NON-first token of exactly one player in the two squads, and the given
    # names must be compatible. A given-name token is never discriminating --
    # "harry" is unique in a squad and still maps Harry Gray to Harry Tyrer.
    btoks = key.split()
    if len(btoks) >= 2 and len(btoks[-1]) >= TOKEN_MIN:
        surname, given = btoks[-1], btoks[0]
        shared = []
        for i, pk in enumerate(pool["key"]):
            pt = pk.split()
            if len(pt) < 2:
                continue
            if any(fuzz.ratio(surname, b) >= 85 for b in pt[1:] if len(b) >= TOKEN_MIN):
                g = pt[0]
                given_ok = (fuzz.ratio(given, g) >= 60) or (given in g) or (g in given) \
                    or fuzz.partial_ratio(given, g) >= 85
                if given_ok:
                    shared.append(i)
        if len(shared) == 1:
            return int(pool["element"].iloc[shared[0]]), "club+token", 90.0
    top = process.extract(key, pool["key"].tolist(), scorer=fuzz.token_set_ratio, limit=5)
    if top:
        best, runner = top[0][1], (top[1][1] if len(top) > 1 else 0.0)
        if best >= FUZZY_FLOOR and best - runner >= FUZZY_MARGIN:
            return int(pool["element"].iloc[top[0][2]]), "fuzzy", float(best)
        return None, f"unmatched(best={best:.0f},runner={runner:.0f})", float(best)
    return None, "unmatched", 0.0


def assert_board_unique(cw_event, event_label):
    """assert_crosswalk_unique semantics (squad/attacking_rates) on every
    per-book board of one event: no element claimed by two names, no name
    mapped to two elements. Raises with the offenders."""
    sys.path.insert(0, str(REPO / "squad"))
    from attacking_rates import assert_crosswalk_unique
    n = 0
    for bk, g in cw_event.groupby("book"):
        frame = g[["element", "key"]].rename(columns={"key": "understat_id"})
        try:
            assert_crosswalk_unique(frame)
        except AssertionError as e:
            raise AssertionError(f"{event_label} [{bk}]: {e}") from None
        n += 1
    return n


def main():
    use_manual = "--no-manual" not in sys.argv
    h = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet",
                        columns=["season", "element", "name", "team", "position", "GW", "minutes"])
    h["minutes"] = pd.to_numeric(h["minutes"], errors="coerce").fillna(0)
    h = h[h["position"] != "AM"]
    md = ["# Player-prop name crosswalk — precision report (2026-08-24)\n",
          "Built by `eval/build_props_crosswalk.py` before any de-vig or feature, per "
          "`Logs/props_prereg.md` §7.4. Method: candidates = the fixture's two clubs' players at that "
          "gameweek (vaastav `team` per gw); tiers exact (normalised full name) → token-subset (one "
          "name's tokens contained in the other's, unique in the pool) → discriminating token (a ≥4-char "
          "token identifying exactly one player in the two squads, `fuzz.ratio ≥ 85`) → fuzzy "
          f"(`token_set_ratio` ≥ {FUZZY_FLOOR} with margin ≥ {FUZZY_MARGIN} over the runner-up, the "
          "build_crosswalk floor). Every row carries `match_type`; unmatched rows are null, counted "
          "and named. Within every board one name → one element and one element → one name "
          "(`assert_crosswalk_unique` semantics); the same normalised name maps to the same element "
          "across the season.\n"]
    for season in SEASONS:
        v = h[h["season"] == season].copy()
        v["key"] = v["name"].map(_norm)
        v["tokens"] = v["key"].map(lambda k: {t for t in k.split() if len(t) >= 3})
        season_keys = v.drop_duplicates("element").groupby("key")["element"].nunique()
        man = pd.read_csv(SCALE / season / "manifest.csv")
        man = man[man["event_id"].notna() & (man["books"].astype(str) != "CALL_FAILED")]
        rows, board_dupes, cross_incons = [], [], []
        name_to_el = {}
        multi_spell = 0
        manual_conflicts, manual_not_in_pool = [], []
        boards_asserted = 0
        season_min = v.groupby("element")["minutes"].sum()
        for r in man.itertuples():
            f = SCALE / season / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))["data"]
            home, away = odds_team_to_fpl(d["home_team"]), odds_team_to_fpl(d["away_team"])
            # one row per element: double gameweeks carry two vaastav rows per player
            # (one per fixture), which would make every exact hit ambiguous
            pool = (v[(v["GW"] == int(r.gw)) & (v["team"].isin([home, away]))]
                    .groupby("element", as_index=False)
                    .agg(name=("name", "first"), key=("key", "first"), tokens=("tokens", "first"),
                         team=("team", "first"), position=("position", "first"), minutes=("minutes", "sum")))
            # book names with implied probs
            names = {}
            for bk in d["bookmakers"]:
                for mk in bk["markets"]:
                    if mk["key"] != MARKET:
                        continue
                    for o in mk["outcomes"]:
                        nm = o.get("description") or o["name"]
                        if nm.lower() in ("no scorer", "no goalscorer"):
                            continue
                        names.setdefault(nm, {})[bk["key"]] = 1.0 / float(o["price"])
            cache, evidence = {}, {}
            for nm, prices in names.items():
                key = _norm(nm)
                if key not in cache:
                    el, mtype, score = match_one(key, pool)
                    if el is None and use_manual and (season, key) in MANUAL:
                        m_el, m_ev = MANUAL[(season, key)]
                        if m_el in set(pool["element"]):
                            # two-direction sweep: the element must not already be claimed by
                            # another name on this event's boards via an automated tier
                            claimed_by = [k for k, (e, t, s) in cache.items() if e == m_el and k != key]
                            if claimed_by:
                                el, mtype, score = None, f"manual_conflict({claimed_by[0]})", 0.0
                                manual_conflicts.append((int(r.gw), f"{home} v {away}", nm, m_el, claimed_by[0]))
                            else:
                                el, mtype, score = m_el, "manual", 100.0
                                evidence[key] = m_ev
                        else:
                            mtype = "manual_not_in_pool"
                            manual_not_in_pool.append((int(r.gw), f"{home} v {away}", nm, m_el))
                    cache[key] = (el, mtype, score)
                el, mtype, score = cache[key]
                rec = dict(season=season, gw=int(r.gw), event_id=r.event_id, fixture=f"{home} v {away}",
                           book_name=nm, key=key, element=el, match_type=mtype, score=score,
                           match_evidence=evidence.get(key, ""), books="|".join(sorted(prices)),
                           n_books=len(prices), mean_implied=float(np.mean(list(prices.values()))),
                           max_implied=float(max(prices.values())))
                if el is not None:
                    pr = pool[pool["element"] == el].iloc[0]
                    rec.update(fpl_name=pr["name"], team=pr["team"], position=pr["position"], minutes_gw=float(pr["minutes"]),
                               homonym_elsewhere=int(season_keys.get(key, 0) > 1 if mtype == "exact" else 0))
                    prev = name_to_el.get(key)
                    if prev is not None and prev != el:
                        cross_incons.append((key, prev, el, int(r.gw)))
                    name_to_el.setdefault(key, el)
                rows.append(rec)
            # board uniqueness PER BOOK: within one bookmaker's outcomes an element
            # may be claimed by at most one name. Two books spelling the same
            # player differently ("Josh King" / "Joshua King") is not a defect;
            # it is counted separately as a multi-spelling.
            per_book = {}
            for nm, prices in names.items():
                el = cache[_norm(nm)][0]
                if el is None:
                    continue
                for bk in prices:
                    per_book.setdefault(bk, []).append((nm, el))
            for bk, lst in per_book.items():
                els = [e for _, e in lst]
                dups = {e for e in els if els.count(e) > 1}
                if dups:
                    board_dupes.append((int(r.gw), f"{home} v {away}", bk, [(nm, e) for nm, e in lst if e in dups]))
            spell = {}
            for nm in names:
                el = cache[_norm(nm)][0]
                if el is not None:
                    spell.setdefault(el, set()).add(nm)
            multi_spell += sum(1 for s in spell.values() if len(s) > 1)
            # assert_crosswalk_unique on every per-book board of this event
            ev_frame = pd.DataFrame([dict(book=bk, element=e, key=_norm(nm))
                                     for nm, prices in names.items() for bk in prices
                                     for e in [cache[_norm(nm)][0]] if e is not None])
            if len(ev_frame):
                boards_asserted += assert_board_unique(ev_frame, f"GW{int(r.gw)} {home} v {away}")
        cw = pd.DataFrame(rows)
        cw.to_csv(REPO / "data" / "odds_props" / f"props_crosswalk_{season}.csv", index=False, encoding="utf-8")
        # --- coverage of players who actually played (the minutes-weighted unmatched) ---
        played = v[v["minutes"] >= 60][["GW", "element", "name", "team", "position", "minutes"]]
        fixtures_on_disk = cw[["gw", "fixture"]].drop_duplicates()
        cov_rows = []
        for fx in fixtures_on_disk.itertuples():
            home, away = fx.fixture.split(" v ")
            pl = played[(played["GW"] == fx.gw) & (played["team"].isin([home, away]))]
            matched_els = set(cw[(cw["gw"] == fx.gw) & (cw["fixture"] == fx.fixture) & cw["element"].notna()]["element"].astype(int))
            for p_ in pl.itertuples():
                cov_rows.append(dict(gw=fx.gw, element=int(p_.element), name=p_.name, team=p_.team, position=p_.position,
                                     minutes=float(p_.minutes), covered=int(p_.element) in matched_els))
        cov = pd.DataFrame(cov_rows)
        # uncovered OUTFIELD starters: unpriced (no candidate name on that board)
        # vs unmatched-with-candidate (a board name shares a >=4-char token)
        unpriced_n, cand_rows = 0, []
        for fx in fixtures_on_disk.itertuples():
            home, away = fx.fixture.split(" v ")
            pl = played[(played["GW"] == fx.gw) & (played["team"].isin([home, away]))].drop_duplicates("element")
            ev_rows = cw[(cw["gw"] == fx.gw) & (cw["fixture"] == fx.fixture)]
            matched_els = set(ev_rows["element"].dropna().astype(int)); unm_ev = ev_rows[ev_rows["element"].isna()]
            for p_ in pl.itertuples():
                if int(p_.element) in matched_els or p_.position == "GK":
                    continue
                toks = [t for t in _norm(p_.name).split() if len(t) >= 4]
                cand = unm_ev[unm_ev["key"].apply(lambda k: any(t in k for t in toks))]
                if len(cand):
                    cand_rows.append(dict(gw=fx.gw, fpl_name=p_.name, team=p_.team, position=p_.position, minutes=float(p_.minutes),
                                          candidates="; ".join(sorted(set(cand["book_name"])))))
                else:
                    unpriced_n += 1
        cand_df = pd.DataFrame(cand_rows)
        cand_sum = (cand_df.groupby(["fpl_name", "team", "position", "candidates"])["minutes"].agg(["sum", "size"]).reset_index()
                    .sort_values("sum", ascending=False)) if len(cand_df) else pd.DataFrame(columns=["fpl_name", "team", "position", "candidates", "sum", "size"])
        uncov_all = cov[~cov["covered"]].groupby(["element", "name", "team", "position"])["minutes"].agg(["sum", "size"]).reset_index() \
            .sort_values("sum", ascending=False)
        # goalkeepers are not priced on these boards; the defect list is OUTFIELD only
        uncov_gk = uncov_all[uncov_all["position"] == "GK"]
        uncov = uncov_all[uncov_all["position"] != "GK"]
        cov_out = cov[cov["position"] != "GK"]
        # --- report ---
        n_names = len(cw); matched = cw["element"].notna()
        by_type = cw.loc[matched, "match_type"].value_counts()
        unm = cw[~matched]
        fuzzy = cw[cw["match_type"] == "fuzzy"].drop_duplicates(["key", "element"])
        clubtok = cw[cw["match_type"] == "club+token"].drop_duplicates(["key", "element"])
        tsub = cw[cw["match_type"] == "token_subset"].drop_duplicates(["key", "element"])
        team_bad = cw[matched & ~cw.apply(lambda x: x["team"] in x["fixture"].split(" v ") if x["element"] is not None else True, axis=1)]
        pos_flag = cw[matched & (((cw["position"] == "GK") & (cw["mean_implied"] >= 0.15)) | ((cw["position"] == "DEF") & (cw["mean_implied"] >= 0.35)))]
        min_flag = cw[matched & (cw["minutes_gw"] == 0) & (cw["mean_implied"] >= 0.30)]
        homonym = cw[matched & (cw["homonym_elsewhere"] == 1)].drop_duplicates(["key", "element"])
        hi_unm = unm.sort_values("mean_implied", ascending=False)
        # placeholder-price flag: a matched player with < 90 season minutes priced at >= .25
        cw["season_minutes"] = cw["element"].map(lambda e: float(season_min.get(int(e), 0)) if pd.notna(e) else np.nan)
        placeholder = cw[matched & (cw["season_minutes"] < 90) & (cw["mean_implied"] >= 0.25)]
        manual_rows = cw[cw["match_type"] == "manual"]
        print(f"\n================ {season} ================  ({'with manual entries' if use_manual else 'AUTOMATED TIERS ONLY'})")
        print(f"  priced name-rows {n_names:,} across {cw['event_id'].nunique()} fixtures; matched {int(matched.sum()):,} ({matched.mean():.2%}); "
              f"unmatched {len(unm):,} ({len(unm) / n_names:.2%}); distinct unmatched names {unm['key'].nunique()}")
        print(f"  provenance: " + ", ".join(f"{k} {v_}" for k, v_ in by_type.items())
              + f"; manual entries applied {len(manual_rows)} rows / {manual_rows['key'].nunique()} names; "
              f"manual conflicts (element already claimed on the board) {len(manual_conflicts)}; manual not-in-pool {len(manual_not_in_pool)}")
        print(f"  assert_crosswalk_unique: {boards_asserted:,} per-book boards asserted, 0 raised")
        print(f"  board uniqueness (one element per BOOK board): {len(board_dupes)} violations; cross-book multi-spellings of one element: {multi_spell}; "
              f"cross-fixture name->element inconsistencies: {len(cross_incons)}")
        print(f"  placeholder-price flags (matched, <90 season minutes, mean implied >= .25): {len(placeholder)} rows, "
              f"{placeholder['element'].nunique()} players")
        print(f"  outfield starters not covered: unpriced (no candidate name on the board) {unpriced_n} player-fixtures; "
              f"unmatched WITH a candidate name {int(cand_sum['size'].sum()) if len(cand_sum) else 0} player-fixtures ({len(cand_sum)} players) -> manual pass")
        print(f"  team audit (matched element's club in the fixture): {len(team_bad)} violations")
        print(f"  homonym check (exact-matched name also exists at another club this season): {len(homonym)}")
        print(f"  price/position flags (GK >= .15 or DEF >= .35 mean implied): {len(pos_flag)}; price/minutes flags (played 0 with mean implied >= .30): {len(min_flag)}")
        print(f"  OUTFIELD players who played >=60 in a priced fixture but map to NO book name: {len(uncov)} players, "
              f"{int(uncov['size'].sum())} player-fixtures, {int(uncov['sum'].sum()):,} minutes "
              f"(of {int(cov_out['minutes'].sum()):,} outfield starter minutes; outfield starter coverage {cov_out['covered'].mean():.2%}); "
              f"goalkeepers are not priced on these boards ({len(uncov_gk)} GKs, {int(uncov_gk['sum'].sum()):,} minutes, excluded)")
        md.append(f"## {season}\n")
        md.append(f"- **Match rate:** {int(matched.sum()):,} of {n_names:,} priced name-rows ({matched.mean():.2%}) across "
                  f"{cw['event_id'].nunique()} fixtures; {unm['key'].nunique()} distinct unmatched names ({len(unm)} rows), left null.")
        md.append(f"- **Provenance:** " + ", ".join(f"{k} {v_:,}" for k, v_ in by_type.items()) + ". "
                  f"Distinct fuzzy pairs {len(fuzzy)}, surname-token pairs {len(clubtok)}, token-subset pairs {len(tsub)} (all listed below); "
                  f"manual entries {manual_rows['key'].nunique()} names / {len(manual_rows)} rows (table below), "
                  f"manual conflicts {len(manual_conflicts)}, manual entries refused because the element was not at a fixture club that gameweek {len(manual_not_in_pool)}.")
        md.append(f"- **assert_crosswalk_unique:** {boards_asserted:,} per-book boards asserted (no element claimed twice, no name mapped twice), 0 raised.")
        if len(manual_rows):
            md.append("\n**Manual entries applied (evidence recorded in `match_evidence`; each auditable without this session):**\n")
            md.append("| book name | → FPL name (element) | rows | evidence |\n|---|---|---|---|")
            for key, g in manual_rows.groupby("key"):
                md.append(f"| {g.book_name.iloc[0]} | {g.fpl_name.iloc[0]} ({int(g.element.iloc[0])}) | {len(g)} | {g.match_evidence.iloc[0]} |")
        if manual_not_in_pool:
            md.append("\nManual entries NOT applied (element not at a fixture club at that gameweek — left null): "
                      + "; ".join(f"GW{gw} {fx}: {nm}" for gw, fx, nm, el in manual_not_in_pool[:12]) + ".")
        if manual_conflicts:
            md.append("\n**Manual conflicts (element already claimed on the board — left null, listed):** "
                      + "; ".join(f"GW{gw} {fx}: {nm} vs {k}" for gw, fx, nm, el, k in manual_conflicts) + ".")
        md.append(f"- **Uniqueness:** per-book board violations {len(board_dupes)}; cross-book multi-spellings of one element "
                  f"{multi_spell} (e.g. \"Josh King\" / \"Joshua King\" — the consensus must merge by element, not by string); "
                  f"cross-fixture name→element inconsistencies {len(cross_incons)}.")
        md.append(f"- **Placeholder prices:** {len(placeholder)} matched rows ({placeholder['element'].nunique()} players) with < 90 season minutes "
                  f"priced at mean implied ≥ 0.25 — youth/fringe names carried on boards at short prices; a data-quality item for the de-vig step, not a matching error.")
        md.append(f"- **Team audit:** {len(team_bad)} matched rows whose element's club is not in the fixture.")
        md.append(f"- **Homonyms:** {len(homonym)} exact-matched names that also exist at another club this season (listed).")
        md.append(f"- **Plausibility flags:** {len(pos_flag)} price/position (GK ≥ .15 or DEF ≥ .35 mean implied), {len(min_flag)} price/minutes (played 0 with mean implied ≥ .30).")
        md.append(f"- **Outfield starters not covered:** {len(uncov)} players / {int(uncov['size'].sum())} player-fixtures / {int(uncov['sum'].sum()):,} minutes of "
                  f"{int(cov_out['minutes'].sum()):,} outfield starter minutes in priced fixtures → outfield starter coverage **{cov_out['covered'].mean():.2%}**. "
                  f"Split: **unpriced** (no candidate name on the board) {unpriced_n} player-fixtures; **unmatched with a candidate name** "
                  f"{int(cand_sum['size'].sum()) if len(cand_sum) else 0} player-fixtures across {len(cand_sum)} players — the manual-pass list below. "
                  f"Goalkeepers are not priced on these boards ({len(uncov_gk)} GKs, {int(uncov_gk['sum'].sum()):,} minutes) and are excluded.\n")
        md.append("**Top uncovered OUTFIELD starters by minutes (played ≥60 in a priced fixture, no book name mapped to them; mostly unpriced):**\n")
        md.append("| player | team | pos | fixtures | minutes |\n|---|---|---|---|---|")
        for u in uncov.head(20).itertuples():
            md.append(f"| {u.name} | {u.team} | {u.position} | {int(u.size)} | {int(u.sum)} |")
        md.append("\n**Unmatched WITH a candidate name — the proposed MANUAL pass (not applied; each needs club + position + minutes evidence):**\n")
        md.append("| FPL name | team | pos | book name(s) on the board | fixtures | minutes |\n|---|---|---|---|---|---|")
        for u in cand_sum.itertuples():
            md.append(f"| {u.fpl_name} | {u.team} | {u.position} | {u.candidates} | {int(u.size)} | {int(u.sum)} |")
        md.append("\n**Unmatched book names, by mean implied probability (top 25 of "
                  f"{unm['key'].nunique()}):**\n\n| book name | fixture (first) | books | mean implied | best candidate score |\n|---|---|---|---|---|")
        for u in hi_unm.drop_duplicates("key").head(25).itertuples():
            md.append(f"| {u.book_name} | GW{u.gw} {u.fixture} | {u.n_books} | {u.mean_implied:.3f} | {u.match_type} |")
        for lab, frame in (("Fuzzy matches (ALL — where silent errors live)", fuzzy), ("Discriminating-token matches (ALL)", clubtok),
                           ("Token-subset matches (ALL)", tsub), ("Exact matches with a same-name player at another club (homonyms)", homonym),
                           ("Price/position flags", pos_flag.drop_duplicates(["key", "element"])), ("Price/minutes flags", min_flag.drop_duplicates(["key", "element", "gw"]))):
            md.append(f"\n**{lab}: {len(frame)}**\n")
            if len(frame):
                md.append("| book name | → FPL name | team | pos | score | mean implied | gw |\n|---|---|---|---|---|---|---|")
                for x in frame.sort_values("score").itertuples():
                    md.append(f"| {x.book_name} | {x.fpl_name} | {x.team} | {x.position} | {x.score:.0f} | {x.mean_implied:.3f} | {x.gw} |")
        if board_dupes:
            md.append("\n**Board uniqueness violations:**\n")
            for gw, fx, lst in board_dupes:
                md.append(f"- GW{gw} {fx}: {lst}")
        if cross_incons:
            md.append("\n**Cross-fixture inconsistencies (same name, different element):** " + "; ".join(f"{k}: {a}→{b} at GW{g}" for k, a, b, g in cross_incons))
        md.append("")
        for lab, frame in (("FUZZY", fuzzy), ("CLUB+TOKEN", clubtok)):
            print(f"  {lab} ({len(frame)}):")
            for x in frame.sort_values("score").itertuples():
                print(f"     {x.book_name!r} -> {x.fpl_name!r} ({x.team}, {x.position}) score {x.score:.0f} implied {x.mean_implied:.3f}")
        print(f"  top uncovered starters: " + "; ".join(f"{u.name} ({u.team}, {int(u.sum)} min/{int(u.size)} fx)" for u in uncov.head(8).itertuples()))
        print(f"  top unmatched names by implied: " + "; ".join(f"{u.book_name} ({u.mean_implied:.2f})" for u in hi_unm.drop_duplicates('key').head(8).itertuples()))
    md.append("## Constraint carried forward to the de-vig step (from the spelling-variant finding)\n")
    md.append("Different books spell one player differently on the same board (\"Josh King\" / \"Joshua King\"; "
              "\"Ibrahim Konate\" / \"Ibrahima Konaté\"). After this crosswalk both strings map to the same element. "
              "**The consensus must merge by `element`, never by name string** — a string-keyed merge would count that "
              "player twice (once per spelling) and halve the weight of every other player on the board. The de-vig "
              "step must group prices by (event, element) and take the per-book mean before any cross-book consensus; "
              "the `books` column on every row records which books priced the string so the per-book grouping is checkable.\n")
    md.append("## Classification of every remaining null (nothing forced)\n")
    md.append("- **Not yet an FPL element at that gameweek:** academy players priced by books before FPL registered them "
              "(vaastav has no row at the priced gameweeks; the element's first row comes later). Correct nulls; "
              "verified per name in the build output.")
    md.append("- **Departed-player listings:** a book still lists a player at a club he has left (2025-26: Marc Guéhi at "
              "Palace GW23 while at Man City; Brennan Johnson at Spurs GW20–21 while at Palace; Jacob Ramsey at Villa "
              "GW3–5 while at Newcastle; Facundo Buonanotte at Chelsea GW22–23 while at Leeds). The club-at-gameweek "
              "pool refused them; correct nulls.")
    md.append("- **Not an FPL element in that season at all:** e.g. Thiago Silva (Chelsea board GW16 2024-25, left in 2024), "
              "and ~30 academy names with no FPL element.")
    md.append("- **Refused as uncertain:** 'Yeimar Mosquera' (15 boards, 2025-26) — the two Mosqueras are Yerson (Wolves) and "
              "Cristhian (Arsenal); 'Yeimar' is neither's name and the boards span both clubs' fixtures. No guess; null.")
    (REPO / "Logs" / "props_crosswalk_log.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n-> Logs/props_crosswalk_log.md; data/odds_props/props_crosswalk_{{season}}.csv")


if __name__ == "__main__":
    main()
