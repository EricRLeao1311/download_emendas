from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from download_emendas.auth import AccessTokenStore, hash_token


class AuthTokenStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AccessTokenStore(Path(self.temp_dir.name) / "tokens.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_and_verify_token(self) -> None:
        self.store.add("Token inicial", "segredo-123")
        self.assertTrue(self.store.verify("segredo-123"))
        self.assertFalse(self.store.verify("segredo-errado"))

    def test_hash_is_stable(self) -> None:
        self.assertEqual(
            hash_token("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


if __name__ == "__main__":
    unittest.main()
