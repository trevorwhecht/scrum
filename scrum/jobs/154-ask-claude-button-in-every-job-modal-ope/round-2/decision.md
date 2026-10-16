APPROVE
Restart: scrum dashboard serve.py on port 8765 — verify: curl -sfL localhost:8765/ | grep -F -- 'askForm'
## Rulings
- build.md ruling (no .resolve() on root): accept — registry stores resolved paths.
- build.md ruling (numeric round sort, *.md only): accept — matches spec.
- build.md ruling (..%2F id returns 400): accept — matches criterion 5.
- build.md ruling (button after Open terminal; mobile test list updated): accept — cosmetic.
- Reviewers code/security/ui/ux finding: none; all PASS, check PASS, UI rendered (Rendered: yes in review-ux).
## Follow-ups
- none
## Manual checks
- On a Mac, click Ask Claude on a job and confirm Ghostty (or Terminal.app fallback) opens with claude in the worktree.
## Merge summary
Title: Add Ask Claude button to every job modal
- New POST /api/p/<project>/jobs/<id>/ask endpoint opens claude in Ghostty or Terminal with a prompt listing the job artifacts.
- Dashboard job modal shows an Ask Claude button in every state, with pending, status and error feedback.
- Tests and README updated.
