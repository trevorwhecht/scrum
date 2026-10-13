#!/usr/bin/env bash
# Builds "Trevskills Scrum.app" in ~/Applications. Clicking it starts the dashboard server if it isn't
# running (through a login shell, so `claude` is on PATH for the buttons), then opens the dashboard in its own
# Chrome app window, or the default browser if Chrome isn't installed. Safe to re-run; it replaces the app.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
app="${SCRUM_APP_DIR:-$HOME/Applications}/Trevskills Scrum.app"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cat > "$work/app.applescript" <<'APPLESCRIPT'
on serverUp()
	try
		do shell script "curl -sf -o /dev/null --max-time 1 http://localhost:8765/api/projects"
		return true
	on error
		return false
	end try
end serverUp

on run
	if not serverUp() then
		set cmd to "mkdir -p ~/.claude/trevskills-scrum && nohup python3 ~/.claude/skills/trevskills-scrum/serve.py >> ~/.claude/trevskills-scrum/serve.log 2>&1 &"
		do shell script "/bin/zsh -lc " & quoted form of cmd
		repeat 40 times
			if serverUp() then exit repeat
			delay 0.25
		end repeat
	end if
	if not serverUp() then
		display alert "Trevskills Scrum" message "The dashboard server didn't start. See ~/.claude/trevskills-scrum/serve.log"
		return
	end if
	try
		do shell script "open -na 'Google Chrome' --args --app=http://localhost:8765/dashboard.html"
	on error
		open location "http://localhost:8765/dashboard.html"
	end try
end run
APPLESCRIPT

mkdir -p "$(dirname "$app")"
rm -rf "$app"
osacompile -o "$app" "$work/app.applescript"

python3 "$here/icon.py" "$work/icon.png"
mkdir "$work/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$work/icon.png" --out "$work/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$work/icon.png" --out "$work/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$work/icon.iconset" -o "$app/Contents/Resources/applet.icns"
touch "$app"
echo "Built $app (drag it to your Dock)"
