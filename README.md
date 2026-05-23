# codex-switch

Local Codex account pool switcher.

## Install for local use

```bash
python3 -m pip install -e /Users/huxiaoshuai/Desktop/common/projects/codexSwitch
```

## Commands

```bash
codex-switch add --note "primary"
codex-switch add --next-refresh 2026-05-30 --note "primary"
codex-switch prepare-add --restart-desktop
codex-switch list
codex-switch use user@example.com
codex-switch use user@example.com --no-restart-desktop
codex-switch auto
codex-switch mark user@example.com unavailable
codex-switch refresh user@example.com --next-refresh 2026-06-06
codex-switch current
codex-switch sync-emails
codex-switch restart-desktop
codex-switch-gui
```

The tool stores account snapshots under `~/.codex/account-pool/` and switches the global
`~/.codex/auth.json`. It never prints token values.

Do not use Codex Desktop's "Log out" button when adding another account you want to keep in the
pool. Logout can revoke the previous account's refresh token. Instead, run
`codex-switch prepare-add`; this backs up and removes only the local
`~/.codex/auth.json`, making Codex show the login screen without revoking the saved account.
After logging into the new account, run `codex-switch add`. It will read the reset date from
Codex usage automatically. If usage cannot be read, pass `--next-refresh YYYY-MM-DD` manually.

`codex-switch list` and `codex-switch auto` refresh usage from ChatGPT's Codex usage endpoint
before printing or switching. The displayed `used` percentage matches the expanded Codex Desktop
"Usage remaining" row; `remaining` is calculated as `100 - used`. When the usage endpoint returns
a reset time, `next_refresh_at` is updated from that value.

`codex-switch auto` first advances every account whose `next_refresh_at` is today or earlier:
the account becomes `available`, and `next_refresh_at` moves forward by 7 days until it is in the
future. It then refreshes live usage and switches only to an account whose refreshed status is
`available`, choosing the available account with the earliest next refresh date.

If a saved account's access token has expired, the tool tries to refresh it with the saved
refresh token. If that refresh token is no longer valid, usage stays `unknown`; the account is
not selected by `auto` until you log into that account again and re-add or update its snapshot.

Codex Desktop and its app-server cache auth while they are running. `codex-switch use`,
`codex-switch auto`, and `codex-switch prepare-add` restart Codex Desktop by default so the
running app reloads the switched `~/.codex/auth.json`. Use `--no-restart-desktop` only when you
are switching for a future CLI process and do not need the running Desktop app to change accounts.
The restart supports macOS and Windows. On macOS it also clears Codex app-server/helper child
processes; on Windows it closes `Codex.exe`, then opens the app from common install locations or
falls back to the system `start Codex` command.
