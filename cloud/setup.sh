#!/usr/bin/env bash
# Paste into a claude.ai/code cloud environment's setup script field (README: Cloud lane). Clones or updates this public
# repo to ~/scrum and runs its install.sh, which symlinks the skill and every agent into ~/.claude: one source of truth.
set -euo pipefail
src="${SCRUM_SRC:-$HOME/scrum}"
if [ -d "$src/.git" ]; then git -C "$src" pull --ff-only -q; else git clone -q --depth 1 https://github.com/trevorwhecht/scrum "$src"; fi
"$src/install.sh"
