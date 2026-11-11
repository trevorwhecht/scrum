-- argv: a directory, a job id, then the command's words. Finds the Terminal tab titled "scrum <job id>": leaves it
-- alone while its claude runs; reruns the command in that tab when it sits idle; else opens a new window and titles it.
-- Never activates Terminal or raises a window, so it opens behind the app Trevor is typing in (2026-11-10).
-- Each word is shell-quoted, as in serve.py's NEW_WINDOW_SCRIPT, so nothing in them runs as shell.
on run argv
  set title to "scrum " & item 2 of argv
  set cmd to "cd " & quoted form of item 1 of argv
  set sep to " && "
  repeat with a in items 3 thru -1 of argv
    set cmd to cmd & sep & quoted form of (a as text)
    set sep to " "
  end repeat
  set cmd to cmd & " && exit"
  tell application "Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if custom title of t is title then
          if busy of t then
            set selected of t to true
            return "focused"
          end if
          do script cmd in t
          set selected of t to true
          return "reused"
        end if
      end repeat
    end repeat
    set t to do script cmd
    set custom title of t to title
  end tell
end run
