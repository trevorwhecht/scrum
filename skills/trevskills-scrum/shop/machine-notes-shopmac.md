# Shop Mac

This session runs on the shop MacBook Pro, a remote worker for the main Mac's scrum. Where this file and other notes disagree about this machine, this file wins.

- macOS 12. No Homebrew: never run `brew`.
- Python 3.12 is `~/.local/bin/python3`, uv-managed, so it refuses `pip install` (externally-managed-environment); install a Python tool with `PYTHONUSERBASE="$HOME/.local" /usr/bin/python3 -m pip install --user <name>`. `/usr/bin/python3` is older, so keep `~/.local/bin` first on `PATH`.
- Node 24 darwin-x64 lives in `~/.local` (`~/.local/bin/node`, `npm`, `npx`).
- Playwright runs through Google Chrome, not Playwright's Chromium: `channel: "chrome"`, set from `SCRUM_PW_CHANNEL`.
- Full builds and full test suites are fine here.
- Bash here runs zsh, which reads a colon right after a bare variable name as a modifier, so write a variable before a `:` in braces: `"${C}:refs/heads/..."`.

## Memory, rules and CLAUDE.md are read-only

Shop sessions never write memory notes, rules or CLAUDE.md, even where other instructions say to save a note. The main Mac replaces them on every sync, so a write here is lost. Put anything worth keeping in the job's follow-ups (`followups/*.md` in the job folder).
