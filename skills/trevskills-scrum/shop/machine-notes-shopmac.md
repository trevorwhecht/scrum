# Shop Mac

This session runs on the shop MacBook Pro, a remote worker for the main Mac's scrum. Where this file and other notes disagree about this machine, this file wins.

- macOS 12. No Homebrew: never run `brew`.
- Python 3.12 is `~/.local/bin/python3`, uv-managed, so it refuses `pip install` (externally-managed-environment); install a Python tool with `PYTHONUSERBASE="$HOME/.local" /usr/bin/python3 -m pip install --user <name>`. `/usr/bin/python3` is older, so keep `~/.local/bin` first on `PATH`.
- Node 24 darwin-x64 lives in `~/.local` (`~/.local/bin/node`, `npm`, `npx`).
- There is no Playwright Chromium. Scripted Chrome (Playwright, render.py, headless screenshots) runs Chrome for Testing at `$SCRUM_CHROME`, never the Google Chrome app: Playwright gets it as `executablePath`, else `channel: "chrome"` from `SCRUM_PW_CHANNEL`.
- VectorCraft 0.17.0 is `/Applications/VectorCraft.app`; its MCP server `vectorcraft` (`~/.local/bin/vectorcraft-cli`) is registered for both Claude accounts, and the main Mac's fonts are in `~/Library/Fonts`. Installed by hand on 2026-11-19, so `shop.py` has no step for it.
- Full builds and full test suites are fine here.
- Bash here runs zsh, which reads a colon right after a bare variable name as a modifier, so write a variable before a `:` in braces: `"${C}:refs/heads/..."`.

## Memory, rules and CLAUDE.md are read-only

Shop sessions never write memory notes, rules or CLAUDE.md, even where other instructions say to save a note. The main Mac replaces them on every sync, so a write here is lost. Put anything worth keeping in the job's follow-ups (`followups/*.md` in the job folder).

## Cannot run

Only the main Mac has these, so the main Mac's scrum never sends a job that needs one here (board.py `main_only_terms`). Each bullet is a comma-separated list of terms.

- PhotoCraft, claude-in-chrome, computer use, MCP
- Chrome profile, logged-in Chrome
- .env.prod, prod data, /trevskills-migrate, /trevskills-datafix
- printer, film printing
- iMessage, Messages, Contacts
- instagram.com, youtu.be, youtube.com, tiktok.com
- Keychain, Homebrew, brew, PR merge
- scrum/briefs, scroll-lab, agent draft API, AGENT_API_TOKEN
- Blender, saas-animation, vid-img-editing, Video folder
- yt-dlp, Whisper, video transcript, Instagram reel, YouTube link
- Kind: edit-reel, Kind: edit-animation, Kind: edit-vector, Kind: edit-photo, Kind: edit-embroidery
- Kind: ops-data, Kind: ops-content
- ~/Developer/claude, md-trim
