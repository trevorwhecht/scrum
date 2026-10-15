#!/bin/sh
# Install (or with --uninstall, remove) the launchd agent that runs local/worker.py every 10 minutes.
# Low priority: background process type, nice 10, throttled disk I/O. Log: ~/.claude/trevskills-scrum/worker.log
set -e
LABEL=com.trevskills.scrum-worker
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "$1" = "--uninstall" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi
WORKER="$(cd "$(dirname "$0")" && pwd)/worker.py"
PY="$(command -v python3)"
mkdir -p "$HOME/.claude/trevskills-scrum" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$WORKER</string></array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
  <key>LowPriorityIO</key><true/>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardErrorPath</key><string>$HOME/.claude/trevskills-scrum/worker.err</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL: $PY $WORKER every 10 minutes"
