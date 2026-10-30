# Betbuilder

Premier League team and player stats, match picks and a prediction tracker,
installable as an app at **https://betbuilder.ciarandevine.uk**.

- **Picks** (`index.html`): pick a match, see each team's most likely goalscorer,
  assister, shot on target, player fouled, player committing a foul, two
  bookings, and expected corners. Tap × on anyone not playing.
- **Stats** (`stats.html`): team comparison, game log, players, distance
  covered, match preview and the prediction tracker.

## Data

`data/` is rebuilt by the **Update data** workflow (`.github/workflows/update-data.yml`)
three times a day from the public [FPL Core Insights](https://github.com/olbauday/FPL-Core-Insights)
dataset, the same source the FFAuction app uses:

1. `scripts/build_from_fplci.py` builds the JSON files, and freezes each game's
   predictions in `data/prediction_log.json` until kickoff, then scores them.
2. `scripts/check_data.py` checks the new files (and that no frozen prediction
   changed) before anything is committed.

Run it by hand from **Actions → Update data → Run workflow**.
Next season: change `data/2026-2027` in the workflow to the new season's folder.

## Files

- `assets/dash.js`: loads `data/*.json` and runs the pages' calculations.
- `assets/d3.min.js`: the d3 chart library (v7), bundled so the app works offline.
- `sw.js`, `manifest.webmanifest`, `icons/`: makes it installable and usable offline.
  Bump `VERSION` in `sw.js` after changing the app's own files.
- `CNAME`: the custom domain for GitHub Pages.

For interest, not betting advice.
