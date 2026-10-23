#!/usr/bin/env bash
# Paste into a claude.ai/code cloud environment's setup script field (README: Cloud lane). Clones or updates this public
# repo to ~/scrum and runs its install.sh, which symlinks the skill and every agent into ~/.claude: one source of truth.
set -euo pipefail
src="${SCRUM_SRC:-$HOME/scrum}"
if [ -d "$src/.git" ]; then git -C "$src" pull --ff-only -q; else git clone -q --depth 1 https://github.com/trevorwhecht/scrum "$src"; fi
"$src/install.sh"
# Dashboard browser tests drive Chromium through Node playwright. Never fatal: they skip cleanly without it.
if [ "${SCRUM_SKIP_BROWSER:-}" != 1 ] && ! NODE_PATH="$(npm root -g 2>/dev/null)" node -e 'require("playwright")' 2>/dev/null; then
  { npm install -g playwright >&2 && npx playwright install chromium >&2; } || echo "warning: playwright/chromium install failed; dashboard browser tests will skip" >&2
fi
