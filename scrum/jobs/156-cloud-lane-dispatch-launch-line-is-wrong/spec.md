OBSOLETE: Cloud lane launch line already uses E=(--settings ...) before --cloud, and test_contracts already guards it.

Evidence:
- `skills/trevskills-scrum/SKILL.md` lines 372-377: `E=(--settings "{\"remote\":{\"defaultEnvironmentId\":\"$CE\"}}")` is set first, and the launch is `claude "${E[@]}" --cloud "First run: ... /trevskills-scrum cloud-job $ID $FEAT"`. No `--environment` appears in the Cloud lane.
- `tests/test_contracts.py` `test_skill_cloud_lane` (lines 1486-1510): asserts the `E=(--settings ...)` snippet and the `claude "${E[@]}" --cloud "First run:` line, `assertNotIn("--environment", cloud)`, and `assertNotRegex(cloud, r"--cloud +(-|\"\$)")` (no flag between `--cloud` and its prompt).
