import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol import DictaphoneSession, safe_session_id


class ProtocolTests(unittest.TestCase):
    def test_safe_session_id_replaces_unsafe_characters(self) -> None:
        self.assertEqual(safe_session_id(" ../phone recording? "), "..-phone-recording")

    def test_session_paths_stay_inside_root(self) -> None:
        root = Path("/tmp/dictaphone-test-session")
        session = DictaphoneSession(session_id="session", root=root)
        self.assertEqual(session.audio_path, root / "audio.pcm")
        self.assertEqual(session.transcript_path, root / "transcript.txt")


if __name__ == "__main__":
    unittest.main()
