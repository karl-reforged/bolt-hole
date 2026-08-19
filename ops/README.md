# Automated refresh

`au.reforged.bolt-hole.refresh.plist` runs the guarded refresh at 06:00 each
Sunday in the logged-in user's macOS session. `launchd` coalesces a missed run
and starts it when the Mac next wakes.

The job calls `scheduled_refresh.py`, which:

1. refuses to overwrite any locally modified public-site file;
2. runs `refresh.sh` and requires its recorded health result to be green;
3. uploads the verified properties to D1 and rebuilds the shortlist;
4. writes `docs/site-state.json` from the exact same canonical active/archive
   partition used to render `docs/index.html`;
5. runs `python site_state.py --verify`, rejecting count/date drift, stale status
   claims, missing page assets, or pages that do not consume the canonical state;
6. commits and pushes the complete public-site bundle atomically; and
7. records `data/logs/scheduled_refresh_status.json` and displays a macOS
   notification if any step fails.

`docs/bolt-hole-overview.html`, `docs/system-map.html`, and
`docs/dashboard.html` load `docs/site-state.js`, so their current inventory,
source coverage, scores, and publication date always come from the same
snapshot as the shortlist. The dashboard's 1,296-sale NSW PSI benchmark is
explicitly historical (through December 2024). `docs/top10.html` is an
explicitly labelled 13 March 2026 archive.

Install or reload the checked-in LaunchAgent:

```sh
mkdir -p "$HOME/Library/LaunchAgents"
cp ops/au.reforged.bolt-hole.refresh.plist \
  "$HOME/Library/LaunchAgents/au.reforged.bolt-hole.refresh.plist"
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/au.reforged.bolt-hole.refresh.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/au.reforged.bolt-hole.refresh.plist"
```

The canonical clone must be on `main`, all public-site bundle files must be
clean before the job starts, Chrome must remain installed, and non-interactive
`git push` authentication must be available.
