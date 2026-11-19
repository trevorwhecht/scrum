# Cloud-home tail runs Merge step 7 Scrum map and BigBoy chaining for a done job
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
`lanes/cloud.md` **Cloud-home tail** ends, for a `done` job, with **Fast-forward main** and the Digest check. It skips two Merge step 7 sub-steps that `lanes/merge.md` runs after `stage=done`: **Scrum map** (apply build.md `## Scrum map` lines to `~/.claude/scrum-map.md`) and **BigBoy chaining** (a job with a `parent` runs **BigBoy lane** step 5: tracker, `B ready`, start the next children or the final review). A cloud-merged BigBoy child therefore never chains, and its map lines never land. Job 1175 ran both by judgement.

## Scope
In: in `skills/trevskills-scrum/lanes/cloud.md`, after the closing paragraph's **Fast-forward main** step and before `B digest-due`, add for a `done` job: run Merge step 7's **Scrum map** (build.md arrives via **Artifacts home**), then, when the job has a `parent`, **BigBoy chaining** (**BigBoy lane** step 5 with `ID` and `P` its parent). Pin both in `tests/test_contracts.py` `test_skill_cloud_lane`. Grep `tests/` for the edited sentence's old text and keep any hit passing.
Out: Roadmap chaining (a cloud job has no roadmap step), changes to `lanes/merge.md` or `lanes/bigboy.md`.

## Acceptance criteria
1. `lanes/cloud.md` Cloud-home tail, in the paragraph that runs Fast-forward main for a done job, names **Scrum map** (Merge step 7) and runs it after Fast-forward main. (verify: `test_skill_cloud_lane` asserts the phrase and that it sits after `**Fast-forward main**` and before `B digest-due`)
2. The same paragraph names **BigBoy chaining** for a job with a `parent` (**BigBoy lane** step 5), run after Fast-forward main and before `B digest-due`. (verify: `test_skill_cloud_lane` asserts the phrase and its order)
3. Both apply only to a `done` job: a `needs-human` or `aborted` job with a `pr` runs neither. (verify: `test_skill_cloud_lane` asserts the new text sits inside the `When the job is `done`` paragraph)
4. The existing `Merge ... Step 7 is only B set $ID stage=done` cloud-session line is unchanged: the in-cloud session still skips chaining. (verify: `test_skill_cloud_lane` still passes with its existing phrases)

## Likely files
- `skills/trevskills-scrum/lanes/cloud.md`
- `tests/test_contracts.py` (`test_skill_cloud_lane`)

## Assumptions
Size: about 2 files, 15 lines
Order: Scrum map first, then chaining, both after Fast-forward main and before the Digest check, matching Merge step 7's order.
Unverified: no other test pins the old closing-paragraph text; builder greps `tests/` for `When the job is` before editing.
