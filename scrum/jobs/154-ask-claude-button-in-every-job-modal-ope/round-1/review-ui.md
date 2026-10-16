VERDICT: PASS
Rendered: yes — "Ask Claude" button in the job modal actions (after the job's other actions, before Pause/Abort) visible; opened a job modal at 390 and 1440 px, clicked it, saw POST to /ask and the error line rendered in the existing .error style (osascript missing on this Linux host); no horizontal overflow, button 44px tall.
## Findings
None.
## Notes
- Reuses .btn, .error, .note and the termForm/redraw pattern; no new colours, fonts or icons.
- The tests/test_dashboard_mobile_390_browser.py action list was updated for the new button.
