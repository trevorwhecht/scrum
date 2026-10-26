"""SKILL.md with every moved section's lane file read back in place, so a test pins a phrase wherever it now lives."""
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum"
MOVED = ("setup", "commands", "newjob", "fastlane", "checkgate", "review", "approve", "merge")  # lanes/ files holding sections moved out of SKILL.md
POINTER = re.compile(r"^Read `\$HOME/\.claude/skills/trevskills-scrum/lanes/(\w+)\.md` when this section runs\.$", re.M)


def skill_text():
    text = (SKILL_DIR / "SKILL.md").read_text()

    def body(m):
        lane = (SKILL_DIR / "lanes" / f"{m.group(1)}.md").read_text()
        return lane.split("\n\n", 1)[1].rstrip("\n")
    # Merge keeps steps 1-2 in SKILL.md; its lane file continues at step 3 on the next line
    text = text.replace("\n\nRead `$HOME/.claude/skills/trevskills-scrum/lanes/merge.md`", "\nRead `$HOME/.claude/skills/trevskills-scrum/lanes/merge.md`")
    return POINTER.sub(body, text)
