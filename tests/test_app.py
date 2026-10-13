import struct, subprocess, sys, tempfile, unittest, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
