VERDICT: PASS
Rendered: yes — Askme picker (#blRunAllAskme: Off/1/2/3) and Run all turning to Cancel visible; exercised click Run all, Cancel, re-open, pick 2 (posted {"askme":2}, no post on Cancel) at 390 and 1440 px, button enabled by script since the backlog was empty, run-all call stubbed.
## Findings
(none)
## Notes
- All four picker buttons measure 44x44 at both widths. At 390 px the header row (Backlog, project select, Cancel, picker, close) fits on one line but is tight.
- Picker hides on disarm, and pending state disables Run all and the picker buttons.
