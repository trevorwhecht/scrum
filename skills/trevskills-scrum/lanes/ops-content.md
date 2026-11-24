# Ops lane: content

Read after `lanes/ops.md`, for `Kind: ops-content` (a blog post, a page of site copy). A content job has no code change: it needs Trevor's own story and facts, then a draft he publishes himself. Two approvals (his answers, then the draft) and a ledger; notes are never approval. The ledger is `$F/jobs/$ID/content.md` (ops.md **Ledger**). The orchestrator does every step itself and spawns no agent.

1. **Ledger.** `content.md` in the job folder, created on the first run:
   ```
   Questions: pending | answered <ISO time>
   ## Drafts
   - d<N>: <path> — Trevor: pending | notes | approved
   ## Trevor's notes
   ```
   `## Trevor's notes` holds each of his answers and notes word for word, with the step it answers. A resume reads it first, never re-asks answered questions, and never reuses a draft number (the next one is one more than the highest `d<N>`).
2. **Questions.** `B set $ID stage=spec`. Read `$F/jobs/$ID/feature.md` and the project's content rules (the convention files `$F/project.md` lists, and the global Writing rule). Write the few questions only Trevor can answer (his story, numbers, examples) to `$F/jobs/$ID/questions.md`, then run `B ask $ID '<what the draft needs from him, in plain words, under 40 words; the questions are in the questions.md tab of this job>' --a "Send back with a note=rework $ID \"<answers>\"" --b "Remove this job=abort $ID --cascade" --title CONTENT_QUESTIONS --recommend <key> '<why>'` and stop. His rework note goes into the ledger word for word and sets `Questions: answered <ISO time>`. When feature.md already answers everything, skip the ask, set `Questions: answered <ISO time>` and write why under `## Trevor's notes`.
3. **Draft.** `B set $ID stage=build`. The orchestrator writes the draft itself to `$F/jobs/$ID/draft-<N>.md` (no agent is spawned), from feature.md and Trevor's answers only: his wording stays his, and the global Writing rule for text under a business's name applies (no dashes of any kind, no hyphenated words). Append `- d<N>: <path> — Trevor: pending` to `## Drafts`. When `$F/project.md` has a `- Content draft:` command line, also run it to post the draft to the site as an unpublished draft and record the result under that `d<N>` line; when the line is missing, the file is the draft.
4. **Approval.** Run `B ask $ID 'Draft <N> is ready for your approval: the text is in the draft-<N>.md tab of this job. Approve it, or send notes for the next draft?' --a "Approve=approve $ID" --b "Send back with a note=rework $ID \"<notes>\"" --c "Remove this job=abort $ID --cascade" --title CONTENT_DRAFT --recommend <key> '<why>'` and stop. Notes go into the ledger word for word, mark `d<N>` as `notes`, and start the next draft (`d<N+1>`, back to step 3). Notes are never approval. Only Trevor's approval ends the job: mark `d<N>` as `approved`, then `B set $ID stage=done`.
5. **Publish.** No step here publishes. Trevor publishes the approved draft himself; the final report (ops.md **Finish**) says where the draft is: the path of `draft-<N>.md`, plus the unpublished draft's link when step 3 posted one.
