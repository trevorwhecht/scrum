# Stops

Every `B ask` reads as Issue / Options / Recommended. The question is the Issue; never write the words Issue or Options into it.

- **Issue:** the machine prefix, first and unchanged (`Hard stop: schema — `, `blocked: `, `debug: `, ...), then one plain sentence with no file paths. Name `stop.md`, `ci.md`, `check.md` or `decision.md` by bare name only.
- **Detail:** file lists, logs and anything long go in `jobs/<id>/stop.md` (`$F/jobs/$ID/stop.md`), written before the ask; the question points to it.
- **Options:** the A/B/C trio where it fits: A carry on or merge (`Carry on`, `Try again`, `Merge anyway`), B send back with a note (`Send back with a note`), C remove this job (`Remove this job=abort <id> --cascade`). A `--requeue` option reads `Put back on the backlog`. Labels are plain words, never a bare `Abort`.
- **Recommended:** `--recommend <key> '<why>'` after the last option. `<key>` is the option you advise, picked by your own judgement; `<why>` is one short reason with every `'` removed. It is its own reason, never a `<why>` the question or an option already uses.
- A re-ask passes the same question, options and --recommend, because an ask without `--recommend` drops the advice.
