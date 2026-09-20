"""fbref_export -- parse SAVED FBref competition pages from disk. Zero requests, by construction
and by assertion. Pages here are synthetic, built to FBref's measured structure: over-header
rows, data-stat cells, squad ids in hrefs, a repeated header row mid-table, comment-wrapped
tables, a duplicated `nations` id, results tables carrying the season in their ids, the
"vs " prefix on _against rows, and accented names.
"""
import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fbref_export as fx                                  # noqa: E402
import team_map                                            # noqa: E402


def _page(season="2026-2027", heading_season=True, canonical_season=None, results=True,
          teams=("Arsenal", "Manchester City", "Nottingham"), possession=("58.1", "61.0", "44.2"),
          nations_copies=2, second_nations_rows=None, categories=("standard", "misc")):
    y = season
    head = f"{y} Premier League Stats" if heading_season else "Premier League Stats"
    canon = (f"https://fbref.com/en/comps/9/{canonical_season}/{canonical_season}-Premier-League-Stats"
             if canonical_season else "https://fbref.com/en/comps/9/Premier-League-Stats")
    hrefs = {"Arsenal": "18bb7c10", "Manchester City": "b8fd03ef", "Nottingham": "e4a775cb",
             "Ipswich Town": "b74092de", "Wigan Athletic": "00000000"}

    def squad_rows(prefix=""):
        out = []
        for t, pos in zip(teams, possession):
            hid = hrefs.get(t, "deadbeef")
            out.append(f'<tr><th data-stat="team"><a href="https://fbref.com/en/squads/{hid}/X-Stats">{prefix}{t}</a></th>'
                       f'<td data-stat="players_used">24</td><td data-stat="possession">{pos}</td>'
                       f'<td data-stat="goals">10</td></tr>')
        return "".join(out)

    def table(tid, prefix="", commented=False):
        body = (f'<table class="stats_table" id="{tid}"><thead>'
                f'<tr class="over_header"><th></th><th></th><th></th><th>Performance</th></tr>'
                f'<tr><th data-stat="team">Squad</th><th data-stat="players_used"># Pl</th>'
                f'<th data-stat="possession">Poss</th><th data-stat="goals">Gls</th></tr></thead><tbody>'
                f'{squad_rows(prefix)}'
                f'<tr class="thead"><th data-stat="team">Squad</th><th data-stat="players_used"># Pl</th>'
                f'<th data-stat="possession">Poss</th><th data-stat="goals">Gls</th></tr>'
                f'</tbody></table>')
        return f"<!--{body}-->" if commented else body

    parts = [f"<!DOCTYPE html><html><head><title>{head} | FBref.com</title>"
             f'<link rel="canonical" href="{canon}"></head><body><h1>{head}</h1>'
             '<table id="nav"><tr><td><a href="/en/">Home</a></td></tr></table>']
    if results:
        parts.append(f'<table id="results{y}91_overall"><thead><tr><th data-stat="rank">Rk</th>'
                     f'<th data-stat="team">Squad</th><th data-stat="points">Pts</th></tr></thead><tbody>'
                     + "".join(f'<tr><th data-stat="rank">{i+1}</th><td data-stat="team"><a href="/en/squads/'
                               f'{hrefs.get(t, "deadbeef")}/X">{t}</a></td><td data-stat="points">{30-i}</td></tr>'
                               for i, t in enumerate(teams)) + "</tbody></table>")
    for c in categories:
        parts.append(table(f"stats_squads_{c}_for"))
        parts.append(table(f"stats_squads_{c}_against", prefix="vs ", commented=True))
    nat = ('<table id="nations"><thead><tr><th data-stat="ranker">Rk</th><th data-stat="nationality">Nation</th>'
           '<th data-stat="players"># Players</th></tr></thead><tbody>'
           '<tr><th data-stat="ranker">1</th><td data-stat="nationality">engEngland</td><td data-stat="players">147</td></tr>'
           '</tbody></table>')
    for k in range(nations_copies):
        if k == 1 and second_nations_rows is not None:
            parts.append(nat.replace("147", str(second_nations_rows)))
        else:
            parts.append(f"<!--{nat}-->" if k else nat)
    parts.append("</body></html>")
    return "".join(parts)


CLUBS = {"2026-27": {"Arsenal", "Man City", "Nott'm Forest", "Ipswich Town"},
         "2024-25": {"Arsenal", "Man City", "Nott'm Forest", "Ipswich"}}


@pytest.fixture()
def saved(tmp_path):
    p = tmp_path / "Premier League Stats _ FBref.com.html"
    p.write_text(_page(), encoding="utf-8")
    return p


# ------------------------------------------------------------------ zero requests

def test_the_module_makes_no_requests_by_construction():
    src = inspect.getsource(fx)
    for forbidden in ("import requests", "from requests", "import urllib", "from urllib",
                      "import http", "from http", "read_html(", "import selenium", "from selenium",
                      "playwright", "webdriver", "urlopen(", "socket"):
        assert forbidden not in src, forbidden
    assert "Path(html_path).read_text" in src


# ------------------------------------------------------------------ Stage 1 properties, kept

def test_comment_wrapped_tables_are_found_and_flagged(saved):
    inv = fx.inventory(saved)
    ids = {t["id"]: t for t in inv["tables"]}
    assert ids["stats_squads_standard_against"]["wrapped_in_comment"] is True
    assert ids["stats_squads_standard_for"]["wrapped_in_comment"] is False
    assert inv["comment_blocks_with_tables"] >= 3


def test_repeated_header_rows_are_dropped_and_columns_are_data_stat_names(saved):
    inv = fx.inventory(saved)
    t = {t["id"]: t for t in inv["tables"]}["stats_squads_standard_for"]
    assert t["n_rows"] == 3 and t["columns"] == ["team", "players_used", "possession", "goals"]
    assert t["over_header"]["goals"] == "Performance" and t["header_text"]["possession"] == "Poss"
    assert t["populated"]["possession"] == 3


# ------------------------------------------------------------------ season detection

def test_season_comes_from_the_results_id_when_the_canonical_has_none(saved):
    rep = fx.process_file(saved, CLUBS, write=False)
    assert rep["season"] == "2026-2027"
    ev = rep["season_evidence"]
    assert ev["results_ids"] == ["2026-2027"] and ev["canonical_url"] is None and ev["heading"] == "2026-2027"


def test_a_heading_that_disagrees_with_the_results_id_stops_the_file(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(season="2026-2027").replace("<h1>2026-2027", "<h1>2025-2026"), encoding="utf-8")
    with pytest.raises(fx.FbrefExportError) as ei:
        fx.process_file(p, CLUBS, write=False)
    assert "DISAGREES" in str(ei.value)


def test_no_season_anywhere_stops_the_file(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(heading_season=False, results=False), encoding="utf-8")
    with pytest.raises(fx.FbrefExportError) as ei:
        fx.process_file(p, CLUBS, write=False)
    assert "refusing to guess" in str(ei.value)


def test_a_past_season_page_with_the_season_in_the_canonical_agrees(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(season="2025-2026", canonical_season="2025-2026"), encoding="utf-8")
    rep = fx.process_file(p, {"2025-26": CLUBS["2026-27"]}, write=False)     # club sets are stack-keyed
    assert rep["season"] == "2025-2026" and rep["season_evidence"]["canonical_url"] == "2025-2026"
    assert fx.stack_season("2025-2026") == "2025-26"


def test_a_season_the_stack_does_not_hold_stops_rather_than_skipping_the_name_check(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(season="2011-2012", canonical_season="2011-2012"), encoding="utf-8")
    with pytest.raises(fx.FbrefExportError) as ei:
        fx.process_file(p, CLUBS, write=False)
    assert "cannot be verified" in str(ei.value)


# ------------------------------------------------------------------ duplicates, skips, types

def test_the_duplicate_nations_id_is_skipped_and_said_so(saved):
    rep = fx.process_file(saved, CLUBS, write=False)
    assert "nations" in rep["skipped_tables"]
    assert any("nations: 2 copies with identical content" in n for n in rep["duplicate_notes"])
    assert not any(t["id"].startswith("nations") for t in rep["tables"])


def test_a_duplicate_id_whose_content_differs_is_kept_twice_and_flagged(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(second_nations_rows=999), encoding="utf-8")
    rep = fx.process_file(p, CLUBS, write=False)
    assert any("DIFFERS" in n and "nations__dup2" in n for n in rep["duplicate_notes"])


def test_table_types_and_categories_come_from_the_id(saved):
    rep = fx.process_file(saved, CLUBS, write=False)
    kinds = {t["id"]: (t["category"], t["table_type"]) for t in rep["tables"]}
    assert kinds["stats_squads_standard_for"] == ("standard", "squad_for")
    assert kinds["stats_squads_misc_against"] == ("misc", "squad_against")
    assert kinds["results2026-202791_overall"] == ("results", "results_overall")
    assert rep["categories"] == ["misc", "standard"]


# ------------------------------------------------------------------ names

def test_the_bridge_strips_vs_and_maps_through_the_named_map(saved):
    rep = fx.process_file(saved, CLUBS, write=False)
    t = next(t for t in rep["tables"] if t["id"] == "stats_squads_standard_against")
    assert rep["unmapped"] == {}
    src = inspect.getsource(fx)
    assert "from team_map import FBREF_TEAM_MAP" in src and "FBREF_TEAM_MAP = {" not in src


def test_rows_carry_metadata_first_then_fbref_name_fpl_name_and_squad_id(saved, tmp_path):
    rep = fx.process_file(saved, CLUBS, out_root=tmp_path / "out", write=True)
    p = tmp_path / "out" / "2026-2027" / "standard" / "stats_squads_standard_against.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    assert header[:9] == fx.META_COLS and header[9:] == ["players_used", "possession", "goals", "team_href"]
    assert header.count("team") == 1, "the raw data-stat `team` must not shadow the FPL-name column"
    row = lines[1].split(",")
    assert row[:4] == ["2026-2027", "Premier League", "standard", "squad_against"]
    assert row[6:9] == ["Arsenal", "Arsenal", "18bb7c10"]
    forest = [l for l in lines if "Nottingham" in l][0].split(",")
    assert forest[6:8] == ["Nottingham", "Nott'm Forest"]
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_an_unmapped_club_withholds_the_seasons_csvs_and_is_reported(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(teams=("Arsenal", "Wigan Athletic", "Nottingham")), encoding="utf-8")
    rep = fx.process_file(p, CLUBS, out_root=tmp_path / "out", write=True)
    assert "Wigan Athletic" in rep["unmapped"]
    assert rep["written"] == [] and not (tmp_path / "out").exists()


def test_sheffield_united_is_in_the_map_and_every_target_is_a_real_stack_club_name():
    """The KNOWN_ISSUES #14 tripwire, now for the FBref map: the entry that withheld three
    seasons on 2026-09-20, and every target checked against club names MEASURED from the
    stack rather than typed. A typo on the FPL side fails here, not silently at join time."""
    assert team_map.FBREF_TEAM_MAP["Sheffield United"] == "Sheffield Utd"
    for dead in ("Sheffield Utd", "Newcastle Utd", "Nott'ham Forest"):
        assert dead not in team_map.FBREF_TEAM_MAP, f"{dead}: appears on no saved FBref page"
    from season_stack import load_stack
    known = set(load_stack(columns=["season", "team"])["team"].dropna().unique())
    for src, target in team_map.FBREF_TEAM_MAP.items():
        assert target in known, f"{src!r} -> {target!r} is not a club name in the stack"


def test_the_fpl_side_drift_is_bridged_through_the_fits_alias_not_a_new_map():
    import dixon_coles as dc
    assert dc.ARCHIVE_NAME_ALIAS["Ipswich Town"] == "Ipswich"
    assert fx.bridge_name("Ipswich Town", "2024-25", CLUBS["2024-25"]) == ("Ipswich", "Ipswich Town")
    assert fx.bridge_name("Ipswich Town", "2026-27", CLUBS["2026-27"]) == ("Ipswich Town", "Ipswich Town")
    assert fx.bridge_name("vs Manchester City", "2026-27", CLUBS["2026-27"]) == ("Man City", "Manchester City")
    assert fx.bridge_name("Wigan Athletic", "2026-27", CLUBS["2026-27"]) == (None, "Wigan Athletic")
    assert team_map.FBREF_TEAM_MAP["Nottingham"] == "Nott'm Forest"


# ------------------------------------------------------------------ sidecar, possession, batch

def test_the_sidecar_states_aggregates_no_xg_and_possession_from_standard(saved, tmp_path):
    import json
    fx.process_file(saved, CLUBS, out_root=tmp_path / "out", write=True)
    prov = json.loads((tmp_path / "out" / "2026-2027" / "provenance.json").read_text(encoding="utf-8"))
    s = prov["statement"]
    assert "SEASON AGGREGATES, NOT PER-MATCH" in s and "xG is UNAVAILABLE" in s
    assert "POSSESSION is sourced from the Standard table" in s and "no Passing page" in s
    assert prov["source"].startswith("FBref") and "MANUAL" in prov["source"]
    assert prov["possession_populated"] == "3 of 3 squads (stats_squads_standard_for)"
    assert prov["tables"]["stats_squads_standard_against"]["was_inside_html_comment"] is True
    assert prov["skipped_tables"] == ["nations"]


def test_possession_populated_is_counted_per_season(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(_page(possession=("58.1", "", "")), encoding="utf-8")
    rep = fx.process_file(p, CLUBS, write=False)
    assert rep["possession_populated"] == (1, 3)


def test_batch_processes_every_file_and_reports_failures_without_stopping(tmp_path, monkeypatch):
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "a.html").write_text(_page(season="2026-2027"), encoding="utf-8")
    (folder / "b.html").write_text(_page(season="2024-2025", canonical_season="2024-2025",
                                         teams=("Arsenal", "Ipswich Town", "Nottingham"),
                                         categories=("standard",)), encoding="utf-8")
    (folder / "c.html").write_text(_page(heading_season=False, results=False), encoding="utf-8")
    monkeypatch.setattr(fx, "club_sets", lambda: {"2026-27": CLUBS["2026-27"], "2024-25": CLUBS["2024-25"]})
    res = fx.batch(folder, out_root=tmp_path / "out", write=True)
    assert [r["season"] for r in res["reports"]] == ["2026-2027", "2024-2025"]
    assert len(res["failures"]) == 1 and "c.html" in res["failures"][0]["file"]
    text = fx.summary_text(res)
    assert "missing categories per season:" in text and "2024-2025: misc" in text
    assert "2026-2027: none" in text and "possession populated" in text
    assert "FAILED files:" in text and "wall-clock" in text
    assert (tmp_path / "out" / "2024-2025" / "standard" / "stats_squads_standard_for.csv").exists()
    assert (tmp_path / "out" / "2026-2027" / "misc" / "stats_squads_misc_against.csv").exists()
    import json
    root = json.loads((tmp_path / "out" / "provenance.json").read_text(encoding="utf-8"))
    assert root["seasons_on_disk"] == ["2024-2025", "2026-2027"]
    assert root["files_refused"][0]["file"] == "c.html"
    assert "Coverage starts at 2024-25" in root["coverage_statement"]
    assert "REFUSED by the name-verification guard" in root["coverage_statement"]
    assert "no hand-written club list" in root["coverage_statement"]
