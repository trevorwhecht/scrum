# serve.py stop_same_tests: add checkout-relative cwd to twin key
Lane: lilguy — small change, ~15 added lines in serve.py plus one test
Complex: no

serve.py stop_same_tests: add the checkout-relative cwd to the (project, command, head) twin key so same relative commands run in different subdirectories are not paired (from 1178)

Hard stops: none

## Likely files
- skills/trevskills-scrum/serve.py
- tests/test_serve_waste_reruns.py

## Acceptance criteria
- stop_same_tests groups twins by (project, command, head, checkout-relative cwd); same command in different subdirectories is not a twin
- tests cover it
