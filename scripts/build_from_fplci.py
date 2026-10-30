"""Build the dashboard's data files from the FPL Core Insights dataset
(github.com/olbauday/FPL-Core-Insights, data/2026-2027).

Usage: python3 build_from_fplci.py <path to data/2026-2027> <out dir>
Writes team_games.json (one row per team per finished Premier League match)
and players.json (one row per player per team, season totals) to <out dir>.
Only Premier League matches (tournament == "prem") that are finished are used;
a match whose player stats aren't processed yet is still counted for team
stats but flagged so player totals can lag a few hours.
"""
import csv
import glob
import json
import os
import sys
import math
from datetime import datetime, timedelta, timezone

# Usage: build_from_fplci.py SRC OUT [--log prediction_log.json] [--asof YYYY-MM-DDTHH:MM]
#  --log   the previous prediction log; predictions for games not yet kicked
#          off are added/refreshed, games already kicked off stay frozen, and
#          finished games are scored against what happened.
#  --asof  backtest: treat games from this UTC time on as unplayed.
args = sys.argv[1:]
SRC, OUT = args[0], args[1]
def opt(name):
    return args[args.index(name) + 1] if name in args else None
ASOF = opt("--asof")
LOG_IN = opt("--log")

SHORT_TO_MINE = {"CHE": "CFC", "LIV": "LFC", "BHA": "BRI"}
NAMES = {
    "ARS": "Arsenal", "AVL": "Aston Villa", "BOU": "Bournemouth", "BRE": "Brentford", "BRI": "Brighton",
    "CFC": "Chelsea", "COV": "Coventry", "CRY": "Crystal Palace", "EVE": "Everton", "FUL": "Fulham",
    "HUL": "Hull", "IPS": "Ipswich", "LEE": "Leeds", "LFC": "Liverpool", "MCI": "Man City",
    "MUN": "Man Utd", "NEW": "Newcastle", "NFO": "Nott'm Forest", "SUN": "Sunderland", "TOT": "Spurs",
}


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def code(v):
    n = num(v)
    return str(int(n)) if n is not None else None


team_of_code = {}
for t in rows(os.path.join(SRC, "teams.csv")):
    mine = SHORT_TO_MINE.get(t["short_name"], t["short_name"])
    if mine not in NAMES:
        raise SystemExit(f"Unknown team short name {t['short_name']}")
    team_of_code[code(t["code"])] = mine

gw_dirs = sorted(
    glob.glob(os.path.join(SRC, "By Gameweek", "GW*")),
    key=lambda p: int(os.path.basename(p)[2:]),
)

team_games = []
players = {}  # (player_id, team) -> totals
cards = {}  # (player_id, gw) -> (yellow, red)
pm_records = []  # one row per player per finished PL match, for previews
upcoming = []  # unfinished PL fixtures
finished_all = {}  # every finished PL match, for scoring predictions
NOW = datetime.fromisoformat(ASOF).replace(tzinfo=timezone.utc) if ASOF else datetime.now(timezone.utc)

for d in gw_dirs:
    gw = int(os.path.basename(d)[2:])
    mpath = os.path.join(d, "matches.csv")
    if not os.path.exists(mpath):
        continue
    all_m = rows(mpath)
    for m in all_m:
        if m.get("tournament") == "prem" and (m.get("finished") != "True" or (ASOF and m["kickoff_time"] >= ASOF)):
            upcoming.append({**m, "gw": gw})
    for m in all_m:
        if m.get("tournament") == "prem" and m.get("finished") == "True" and not (ASOF and m["kickoff_time"] >= ASOF):
            finished_all[m["match_id"]] = m
    matches = {
        m["match_id"]: m for m in all_m
        if m.get("tournament") == "prem" and m.get("finished") == "True" and not (ASOF and m["kickoff_time"] >= ASOF)
    }
    if not matches:
        continue

    # the team each player was at during this gameweek
    pteam = {}
    ppath = os.path.join(d, "players.csv")
    for p in rows(ppath):
        pteam[p["player_id"]] = (team_of_code.get(code(p["team_code"])), p)

    # per-player stats in each match
    pms = rows(os.path.join(d, "playermatchstats.csv")) if os.path.exists(os.path.join(d, "playermatchstats.csv")) else []
    agg = {}  # (match_id, team) -> distance m, sprints
    for r in pms:
        if r["match_id"] not in matches:
            continue
        team, p = pteam.get(r["player_id"], (None, None))
        if not team:
            continue
        mins = num(r["minutes_played"]) or 0
        a = agg.setdefault((r["match_id"], team), {"dist": 0.0, "sprints": 0.0, "have": False})
        if r["distance_covered"] != "":
            a["dist"] += num(r["distance_covered"]) or 0
            a["sprints"] += num(r["number_of_sprints"]) or 0
            a["have"] = True
        if mins <= 0:
            continue
        pm_records.append({
            "player_id": r["player_id"], "team": team, "match_id": r["match_id"], "gw": gw, "cards": 0,
            "date": matches[r["match_id"]]["kickoff_time"], "minutes": mins,
            "xg": num(r["xg"]) or 0, "xa": num(r["xa"]) or 0, "sot": num(r["shots_on_target"]) or 0,
            "fouls": num(r["fouls_committed"]) or 0, "fouled": num(r["was_fouled"]) or 0,
            "goals": num(r["goals"]) or 0, "assists": num(r["assists"]) or 0,
        })
        key = (r["player_id"], team)
        pl = players.setdefault(key, {
            "player_id": r["player_id"], "name": p["web_name"],
            "full_name": f"{p['first_name']} {p['second_name']}".strip(),
            "position": p.get("position", ""), "team": team, "team_name": NAMES[team],
            "apps": 0, "starts": 0, "minutes": 0, "goals": 0, "assists": 0, "shots": 0, "sot": 0,
            "xg": 0.0, "xa": 0.0, "fouls": 0, "fouled": 0, "yellow": 0, "red": 0, "dist_m": 0.0, "dist_mins": 0, "sprints": 0, "top_speed": None,
            "gws": set(),
        })
        pl["apps"] += 1
        pl["starts"] += 1 if num(r["start_min"]) == 0 else 0
        pl["minutes"] += int(mins)
        pl["goals"] += int(num(r["goals"]) or 0)
        pl["assists"] += int(num(r["assists"]) or 0)
        pl["shots"] += int(num(r["total_shots"]) or 0)
        pl["sot"] += int(num(r["shots_on_target"]) or 0)
        pl["xg"] += num(r["xg"]) or 0
        pl["xa"] += num(r["xa"]) or 0
        pl["fouls"] += int(num(r["fouls_committed"]) or 0)
        pl["fouled"] += int(num(r["was_fouled"]) or 0)
        pl["gws"].add(gw)
        if r["distance_covered"] != "":
            pl["dist_m"] += num(r["distance_covered"]) or 0
            pl["dist_mins"] += int(mins)
            pl["sprints"] += int(num(r["number_of_sprints"]) or 0)
            ts = num(r["top_speed"])
            if ts is not None and (pl["top_speed"] is None or ts > pl["top_speed"]):
                pl["top_speed"] = ts

    # cards come from the FPL per-gameweek file (playermatchstats has none)
    gpath = os.path.join(d, "player_gameweek_stats.csv")
    if os.path.exists(gpath):
        for r in rows(gpath):
            cards[(r["id"], gw)] = (int(num(r["yellow_cards"]) or 0), int(num(r["red_cards"]) or 0))

    for mid, m in matches.items():
        h, a_ = team_of_code[code(m["home_team"])], team_of_code[code(m["away_team"])]
        for side, opp, team, other in (("home", "away", h, a_), ("away", "home", a_, h)):
            gf, ga = int(num(m[f"{side}_score"])), int(num(m[f"{opp}_score"]))
            ag = agg.get((mid, team), {})
            dist = round(ag["dist"] / 1000, 1) if ag.get("have") else None
            val = lambda k, s=side: (int(num(m[f"{s}_{k}"])) if num(m[f"{s}_{k}"]) is not None else None)
            team_games.append({
                "match_id": mid, "date": m["kickoff_time"][:10], "gw": gw,
                "team": team, "team_name": NAMES[team], "opponent": NAMES[other],
                "venue": "Home" if side == "home" else "Away",
                "gf": gf, "ga": ga, "result": "W" if gf > ga else ("L" if gf < ga else "D"),
                "poss": val("possession"), "shots": val("total_shots"), "sot": val("shots_on_target"),
                "soff": val("shots_off_target"), "sblk": val("blocked_shots"),
                "xg": round(num(m[f"{side}_expected_goals_xg"]) or 0, 2),
                "xga": round(num(m[f"{opp}_expected_goals_xg"]) or 0, 2),
                "corners": val("corners"), "fouls": val("fouls_committed"), "fouls_won": val("fouls_committed", opp), "offsides": val("offsides"),
                "yellow": val("yellow_cards"), "red": val("red_cards"),
                "distance_km": dist, "sprints": int(ag["sprints"]) if ag.get("have") else None,
                "player_stats_processed": m.get("player_stats_processed") == "True",
            })

seen_pg = set()
for rec in pm_records:
    k = (rec["player_id"], rec["gw"])
    if k in seen_pg:
        continue
    seen_pg.add(k)
    y, rc = cards.get(k, (0, 0))
    rec["cards"] = 1 if (y or rc) else 0

out_players = []
for (pid, team), p in players.items():
    for gw in p.pop("gws"):
        y, rc = cards.get((pid, gw), (0, 0))
        p["yellow"] += y
        p["red"] += rc
    p["xg"] = round(p["xg"], 2)
    p["xa"] = round(p["xa"], 2)
    p["distance_km"] = round(p.pop("dist_m") / 1000, 1)
    dm = p.pop("dist_mins")
    p["km_per90"] = round(p["distance_km"] / dm * 90, 2) if dm >= 90 else None
    out_players.append(p)

team_games.sort(key=lambda r: (r["date"], r["match_id"], r["venue"] != "Home"))
out_players.sort(key=lambda r: (r["team"], -r["minutes"]))
os.makedirs(OUT, exist_ok=True)
json.dump(team_games, open(os.path.join(OUT, "team_games.json"), "w"), separators=(",", ":"))
json.dump(out_players, open(os.path.join(OUT, "players.json"), "w"), separators=(",", ":"), ensure_ascii=False)

# ---------------------------------------------------------------------------
# Previews for upcoming fixtures (kickoff in the next 8 days).
# A simple, transparent model, not a betting model:
#  - each player's rate per 90 for xG (scoring), xA (assisting), shots on
#    target, fouls committed and fouls won, shrunk toward his position's
#    average with 270 minutes' worth of prior so small samples don't dominate;
#  - expected minutes = his average minutes over the team's last 3 league
#    games (0 when he didn't play), times FPL's chance of playing (injured,
#    suspended or departed = 0);
#  - scaled by the opponent (what they concede per game against the league
#    average, shrunk toward average) and by home/away (league-wide ratio);
#  - chance of at least one = 1 - e^(-expected count) (Poisson).
# Corners: each side's expected corners = its corners won per game x the
# opponent's corners conceded per game / league average, with the home/away
# ratio; totals use a Poisson distribution.
# ---------------------------------------------------------------------------
PRIOR_90 = 3.0
OPP_K = 5.0
status = {}
sp = os.path.join(SRC, "playerstats.csv")
if os.path.exists(sp):
    for r in rows(sp):
        g = num(r.get("gw")) or 0
        if r["id"] not in status or g >= status[r["id"]][0]:
            status[r["id"]] = (g, r.get("status", "a"), num(r.get("chance_of_playing_next_round")), r.get("news", ""))
current_team = {}
for p in rows(os.path.join(SRC, "players.csv")):
    current_team[p["player_id"]] = (team_of_code.get(code(p["team_code"])), p)

def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0

tg_by_team = {}
for r in team_games:
    tg_by_team.setdefault(r["team"], []).append(r)
lg = {k: mean(r[k] for r in team_games if r[k] is not None) for k in ("xg", "sot", "fouls", "fouls_won", "corners")}
home_rows = [r for r in team_games if r["venue"] == "Home"]
away_rows = [r for r in team_games if r["venue"] == "Away"]
venue_ratio = {}
for k in ("xg", "sot", "fouls", "fouls_won", "corners"):
    h, a = mean(r[k] for r in home_rows), mean(r[k] for r in away_rows)
    venue_ratio[k] = {"Home": h / lg[k] if lg[k] else 1, "Away": a / lg[k] if lg[k] else 1}

def opp_factor(opp, conceded_key, league_key):
    """How much the opponent allows of a stat vs the league, shrunk to 1."""
    g = tg_by_team.get(opp, [])
    n = len(g)
    allowed = mean(r[conceded_key] for r in g) if n else lg[league_key]
    return ((allowed * n + lg[league_key] * OPP_K) / (n + OPP_K)) / lg[league_key]

# what each team concedes: xG against, SoT against, fouls committed against it, fouls it wins
for team, g in tg_by_team.items():
    by_mid = {r["match_id"]: r for r in team_games if r["team"] != team}
    for r in g:
        o = by_mid.get(r["match_id"])
        r["_sot_against"] = o["sot"] if o else None
        r["_corners_against"] = o["corners"] if o else None

pos_rate = {}
per_player = {}
for rec in pm_records:
    per_player.setdefault((rec["player_id"], rec["team"]), []).append(rec)
for (pid, team), recs in per_player.items():
    pos = current_team.get(pid, (None, {}))[1].get("position", "")
    a = pos_rate.setdefault(pos, {"mins": 0, "xg": 0, "xa": 0, "sot": 0, "fouls": 0, "fouled": 0, "cards": 0})
    for rec in recs:
        a["mins"] += rec["minutes"]
        for k in ("xg", "xa", "sot", "fouls", "fouled", "cards"):
            a[k] += rec[k]
for pos, a in pos_rate.items():
    for k in ("xg", "xa", "sot", "fouls", "fouled", "cards"):
        a[k + "_90"] = a[k] / a["mins"] * 90 if a["mins"] else 0

def poisson_at_least_one(lam):
    return 1 - math.exp(-max(lam, 0))

def poisson_over(lam, line):
    k = int(math.floor(line))
    cdf = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))
    return 1 - cdf

previews, fixtures_out = [], []
seen = set()
for m in sorted(upcoming, key=lambda m: m["kickoff_time"]):
    if m["match_id"] in seen:
        continue
    seen.add(m["match_id"])
    try:
        ko = datetime.fromisoformat(m["kickoff_time"].replace("Z", "")).replace(tzinfo=timezone.utc)
    except ValueError:
        continue
    if not (NOW - timedelta(hours=3) <= ko <= NOW + timedelta(days=8)):
        continue
    h, a_ = team_of_code[code(m["home_team"])], team_of_code[code(m["away_team"])]
    fx = {"fixture_id": m["match_id"], "kickoff": m["kickoff_time"], "gw": m["gw"],
          "home": h, "away": a_, "home_name": NAMES[h], "away_name": NAMES[a_],
          "label": f"{NAMES[h]} v {NAMES[a_]}"}
    # corners
    lam = {}
    for team, opp, venue in ((h, a_, "Home"), (a_, h, "Away")):
        g, og = tg_by_team.get(team, []), tg_by_team.get(opp, [])
        cf = (mean(r["corners"] for r in g) * len(g) + lg["corners"] * OPP_K) / (len(g) + OPP_K)
        ca = (mean(r["_corners_against"] for r in og) * len(og) + lg["corners"] * OPP_K) / (len(og) + OPP_K)
        lam[venue] = cf * ca / lg["corners"] * venue_ratio["corners"][venue]
    tot = lam["Home"] + lam["Away"]
    fx.update({"corners_home": round(lam["Home"], 1), "corners_away": round(lam["Away"], 1), "corners_total": round(tot, 1)})
    for line in (7.5, 8.5, 9.5, 10.5, 11.5):
        fx[f"corners_over_{str(line).replace('.', '_')}"] = round(poisson_over(tot, line), 3)
    fixtures_out.append(fx)

    for team, opp, venue in ((h, a_, "Home"), (a_, h, "Away")):
        recent = sorted(tg_by_team.get(team, []), key=lambda r: r["date"])[-3:]
        recent_ids = {r["match_id"] for r in recent}
        f_score = opp_factor(opp, "xga", "xg") * venue_ratio["xg"][venue]
        f_sot = opp_factor(opp, "_sot_against", "sot") * venue_ratio["sot"][venue]
        f_foul = opp_factor(opp, "fouls_won", "fouls") * venue_ratio["fouls"][venue]
        f_fouled = opp_factor(opp, "fouls", "fouls_won") * venue_ratio["fouls_won"][venue]
        for pid, (cur_team, p) in current_team.items():
            if cur_team != team:
                continue
            recs = per_player.get((pid, team), [])
            if not recs:
                continue
            exp_mins = sum(r["minutes"] for r in recs if r["match_id"] in recent_ids) / max(len(recent), 1)
            st = status.get(pid, (0, "a", None, ""))
            avail = 1.0 if st[1] == "a" else ((st[2] or 0) / 100 if st[1] == "d" else 0.0)
            exp_mins *= avail
            if exp_mins < 10:
                continue
            mins = sum(r["minutes"] for r in recs)
            pr = pos_rate.get(p.get("position", ""), {})
            def rate(k):
                tot_k = sum(r[k] for r in recs)
                return (tot_k + pr.get(k + "_90", 0) * PRIOR_90) / (mins / 90 + PRIOR_90)
            share = exp_mins / 90
            lam_g = rate("xg") * share * f_score
            lam_a = rate("xa") * share * f_score
            lam_s = rate("sot") * share * f_sot
            lam_f = rate("fouls") * share * f_foul
            lam_w = rate("fouled") * share * f_fouled
            # bookings: his card rate, scaled like fouls (a side that wins lots of fouls draws more cards)
            lam_c = rate("cards") * share * f_foul
            previews.append({
                "fixture_id": m["match_id"], "player_id": pid, "name": p["web_name"],
                "team": team, "team_name": NAMES[team], "position": p.get("position", ""),
                "exp_mins": round(exp_mins), "availability": st[1], "news": st[3],
                "season_mins": int(mins),
                "p_score": round(poisson_at_least_one(lam_g), 3),
                "p_assist": round(poisson_at_least_one(lam_a), 3),
                "p_sot": round(poisson_at_least_one(lam_s), 3),
                "p_foul": round(poisson_at_least_one(lam_f), 3),
                "p_fouled": round(poisson_at_least_one(lam_w), 3),
                "p_card": round(poisson_at_least_one(lam_c), 3),
                "exp_fouls": round(lam_f, 2), "exp_fouled": round(lam_w, 2),
            })

json.dump(previews, open(os.path.join(OUT, "previews.json"), "w"), separators=(",", ":"), ensure_ascii=False)
json.dump(fixtures_out, open(os.path.join(OUT, "fixtures.json"), "w"), separators=(",", ":"))
for r in team_games:
    r.pop("_sot_against", None)
    r.pop("_corners_against", None)
json.dump(team_games, open(os.path.join(OUT, "team_games.json"), "w"), separators=(",", ":"))
print(f"previews: {len(fixtures_out)} upcoming fixtures, {len(previews)} player rows")

# ---------------------------------------------------------------------------
# Prediction log: freeze each fixture's last pre-kickoff prediction, then
# score it once the match is finished.
# ---------------------------------------------------------------------------
log = {}
if LOG_IN and os.path.exists(LOG_IN):
    for e in json.load(open(LOG_IN)):
        log[e["fixture_id"]] = e
made_at = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
refreshed = 0
for fx in fixtures_out:
    ko = datetime.fromisoformat(fx["kickoff"].replace("Z", "")).replace(tzinfo=timezone.utc)
    if ko <= NOW:
        continue  # already kicked off: keep whatever was frozen before
    keep = ("player_id", "name", "team", "team_name", "position", "exp_mins", "availability",
            "p_score", "p_assist", "p_sot", "p_foul", "p_fouled", "p_card")
    log[fx["fixture_id"]] = {
        **{k: v for k, v in fx.items()}, "made_at": made_at,
        "players": [{k: p[k] for k in keep} for p in previews if p["fixture_id"] == fx["fixture_id"]],
    }
    refreshed += 1

acts = {}
for rec in pm_records:
    acts[(rec["match_id"], rec["player_id"])] = rec
res_rows, res_fixtures = [], []
for fid, e in sorted(log.items(), key=lambda kv: kv[1]["kickoff"]):
    m = finished_all.get(fid)
    status_ = "pending" if not m else ("final" if m.get("player_stats_processed") == "True" else "provisional")
    fxrow = {k: e[k] for k in ("fixture_id", "label", "kickoff", "gw", "home", "away", "home_name", "away_name",
                               "made_at", "corners_home", "corners_away", "corners_total")}
    fxrow.update({k: v for k, v in e.items() if k.startswith("corners_over_")})
    fxrow["status"] = status_
    fxrow["players_predicted"] = len(e["players"])
    if m:
        ch, ca = int(num(m["home_corners"]) or 0), int(num(m["away_corners"]) or 0)
        fxrow.update({"actual_corners_home": ch, "actual_corners_away": ca, "actual_corners_total": ch + ca,
                      "score": f"{int(num(m['home_score']))}–{int(num(m['away_score']))}"})
    res_fixtures.append(fxrow)
    if not m:
        continue
    for p in e["players"]:
        a = acts.get((fid, p["player_id"]))
        row = {"fixture_id": fid, "player_id": p["player_id"], "name": p["name"], "team": p["team"],
               "team_name": p["team_name"], "position": p["position"], "exp_mins": p["exp_mins"],
               "minutes": int(a["minutes"]) if a else 0, "status": status_}
        for k, ak in (("score", "goals"), ("assist", "assists"), ("sot", "sot"), ("foul", "fouls"), ("fouled", "fouled"), ("card", "cards")):
            row["p_" + k] = p.get("p_" + k)  # None for predictions logged before this category existed
            row["hit_" + k] = 1 if a and a[ak] > 0 else 0
            row["n_" + k] = int(a[ak]) if a else 0
        res_rows.append(row)

log_out = sorted(log.values(), key=lambda e: e["kickoff"])
json.dump(log_out, open(os.path.join(OUT, "prediction_log.json"), "w"), separators=(",", ":"), ensure_ascii=False)
json.dump(res_fixtures, open(os.path.join(OUT, "pred_fixtures.json"), "w"), separators=(",", ":"), ensure_ascii=False)
json.dump(res_rows, open(os.path.join(OUT, "pred_results.json"), "w"), separators=(",", ":"), ensure_ascii=False)
done = [f for f in res_fixtures if f["status"] != "pending"]
print(f"prediction log: {len(log_out)} fixtures ({refreshed} refreshed before kickoff), "
      f"{len(done)} scored ({sum(f['status'] == 'provisional' for f in done)} provisional)")
for f in done:
    print(f"  scored: {f['label']} {f.get('score')} [{f['status']}] corners {f['corners_total']} predicted / {f['actual_corners_total']} actual")

gws = sorted({r["gw"] for r in team_games})
print(f"team_games: {len(team_games)} rows ({len(team_games)//2} matches), gameweeks {gws[0]}-{gws[-1]}")
print(f"players: {len(out_players)} rows")
missing = sorted({r['match_id'] for r in team_games if r['distance_km'] is None})
print(f"matches without distance: {missing}")
print(f"matches awaiting player stats: {sorted({r['match_id'] for r in team_games if not r['player_stats_processed']})}")
