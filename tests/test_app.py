import json, os, struct, subprocess, sys, tempfile, unittest, zlib
from pathlib import Path
from unittest import mock

os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))


class BuildLockWaitTest(unittest.TestCase):
    def flags(self, jobs, markers):
        """buildLockWait per job id, with a `.waiting` dir holding `markers` ({pid: cwd}) beside a temp lock."""
        import serve
        with tempfile.TemporaryDirectory() as t:
            t = Path(t).resolve()
            if markers is not None:
                (t / "build.lock.waiting").mkdir()
                for pid, cwd in markers.items():
                    (t / "build.lock.waiting" / str(pid)).write_text(str(cwd))
            (t / "board.json").write_text(json.dumps({"jobs": jobs}))
            with mock.patch.dict(os.environ, {"SCRUM_BUILD_LOCK": str(t / "build.lock")}), \
                    mock.patch.object(serve, "activity", return_value={}):
                return {j["id"]: j.get("buildLockWait") for j in serve.board_with_activity(t, "p")["jobs"]}

    def test_build_lock_wait_flag(self):
        wt = tempfile.mkdtemp()
        sub = Path(wt) / "pkg"
        sub.mkdir()
        job = {"id": "1-a", "stage": "check", "worktree": wt}
        self.assertEqual(self.flags([job], {os.getpid(): wt}), {"1-a": True})
        self.assertEqual(self.flags([job], {os.getpid(): sub}), {"1-a": True})

    def test_build_lock_wait_ignores_stale_other_stage(self):
        wt = tempfile.mkdtemp()
        other = tempfile.mkdtemp()
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        job = {"id": "1-a", "stage": "check", "worktree": wt}
        self.assertEqual(self.flags([job], {dead.pid: wt}), {"1-a": None})  # dead pid
        self.assertEqual(self.flags([job], {os.getpid(): other}), {"1-a": None})  # another path
        self.assertEqual(self.flags([{**job, "stage": "build"}], {os.getpid(): wt}), {"1-a": None})
        nowt = {"id": "1-a", "stage": "check"}
        self.assertEqual(self.flags([nowt], {os.getpid(): wt}), {"1-a": None})
        self.assertEqual(self.flags([job], None), {"1-a": None})  # no .waiting dir


class IconTest(unittest.TestCase):
    def test_icon_is_a_valid_1024px_png_with_the_board_colours(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "icon.png"
            subprocess.run([sys.executable, str(ROOT / "app" / "icon.py"), str(out)], check=True)
            data = out.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", data[16:24])
            self.assertEqual((width, height), (1024, 1024))
            raw = zlib.decompress(b"".join(data[i + 8:i + 8 + struct.unpack(">I", data[i:i + 4])[0]]
                                            for i in self.chunks(data, b"IDAT")))
            self.assertIn(bytes((0x1e, 0x84, 0x49, 255)), raw)  # pass green card
            self.assertEqual(raw[1 + 3], 0)  # corner pixel is transparent (rounded square)

    @staticmethod
    def chunks(data, kind):
        i = 8
        while i < len(data):
            length = struct.unpack(">I", data[i:i + 4])[0]
            if data[i + 4:i + 8] == kind:
                yield i
            i += 12 + length


if __name__ == "__main__":
    unittest.main()
