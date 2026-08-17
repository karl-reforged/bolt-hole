# Automated refresh

`au.reforged.bolt-hole.refresh.plist` runs the guarded refresh at 06:00 each
Sunday in the logged-in user's macOS session. `launchd` coalesces a missed run
and starts it when the Mac next wakes.

The job calls `scheduled_refresh.py`, which:

1. refuses to overwrite a locally modified `docs/index.html`;
2. runs `refresh.sh` and requires its recorded health result to be green;
3. uploads the verified properties to D1 and rebuilds the shortlist;
4. commits and pushes only `docs/index.html`; and
5. records `data/logs/scheduled_refresh_status.json` and displays a macOS
   notification if any step fails.

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

The canonical clone must be on `main`, `docs/index.html` must be clean before
the job starts, Chrome must remain installed, and non-interactive `git push`
authentication must be available.
