# Cloud lane skips the Prod check

Cloud lane skips the Prod check: a cloud-job Merge step 7 is only B set done, and cloud-home runs no Prod check, so a spec with Prod runs (datafix dev and prod runs) merges with the data never fixed. Seen on onewitharts job 1539 (PR 1070, run by hand in cloud-home). Fix: cloud-home runs Merge step 7 Prod check (deploy wait, Prod runs via prod-ok, smoke check) for a merged job whose decision.md or spec.md lists Prod runs, before calling it live; also the cloud approver wrote no decision.md for 1539.

Files: skills/trevskills-scrum/lanes/cloud.md, skills/trevskills-scrum/lanes/merge.md
