"""Checks the freshly built data before it is committed, then writes data/meta.json.

Usage: python3 check_data.py <new data dir> <previous prediction_log.json>
Exits non-zero (so nothing is committed) if a hard check fails:
  - every club appears in team_games, and each match's possessions add to 100
  - every chance (keys starting p_) is empty or between 0 and 1
  - no frozen prediction changed: every game in the previous log that has
    kicked off is still in the new log with the same players and made_at
Player-vs-team totals are reported only (small gaps are normal).
"""
import json, os, sys, collections
from datetime import datetime, timezone

new_dir, prev_log = sys.argv[1], sys.argv[2]
load = lambda n: json.load(open(os.path.join(new_dir, n)))
fail = []

tg = load("team_games.json")
if len({r["team"] for r in tg}) != 20:
    fail.append(f"team_games has {len({r['team'] for r in tg})} clubs, expected 20")
by_match = collections.defaultdict(list)
for r in tg:
    by_match[r["match_id"]].append(r)
bad = [m for m, v in by_match.items() if len(v) != 2 or sum(x["poss"] or 0 for x in v) != 100]
if bad:
    fail.append(f"possession doesn't add to 100 in: {bad[:5]}")

for name in ("previews.json", "pred_results.json"):
    for r in load(name):
        for k, v in r.items():
            if k.startswith("p_") and v is not None and not (0 <= v <= 1):
                fail.append(f"{name}: {k}={v} for {r.get('name')}")
                break

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
if os.path.exists(prev_log):
    old = {e["fixture_id"]: e for e in json.load(open(prev_log))}
    new = {e["fixture_id"]: e for e in load("prediction_log.json")}
    for fid, e in old.items():
        if e["kickoff"][:16] <= now:
            n = new.get(fid)
            if not n or n["players"] != e["players"] or n["made_at"] != e["made_at"]:
                fail.append(f"frozen prediction changed or dropped: {fid}")

# soft check
pl = load("players.json")
tt = collections.defaultdict(lambda: [0, 0, 0, 0]); pt = collections.defaultdict(lambda: [0, 0, 0, 0])
for r in tg:
    a = tt[r["team"]]; a[0] += r["shots"] or 0; a[1] += r["sot"] or 0; a[2] += r["yellow"] or 0; a[3] += r["fouls"] or 0
for p in pl:
    a = pt[p["team"]]; a[0] += p["shots"]; a[1] += p["sot"]; a[2] += p["yellow"]; a[3] += p["fouls"]
gaps = {t: (tt[t], pt[t]) for t in tt if any(abs(x - y) > 2 for x, y in zip(tt[t], pt[t]))}
if gaps:
    print("note: player totals differ from team totals (shots, on target, yellows, fouls):", gaps)

if fail:
    print("CHECK FAILED:\n  " + "\n  ".join(fail))
    sys.exit(1)

gws = sorted({r["gw"] for r in tg})
json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "gw_first": gws[0], "gw_last": gws[-1], "matches": len(by_match)},
          open(os.path.join(new_dir, "meta.json"), "w"))
print(f"checks passed: {len(by_match)} matches, gameweeks {gws[0]}-{gws[-1]}")
