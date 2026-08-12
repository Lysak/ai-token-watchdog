import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class KeychainHelperDisabledTests(unittest.TestCase):
    def test_setup_does_not_invoke_security(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            marker = tmp / "security-called"
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fake_security = fake_bin / "security"
            fake_security.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
            fake_security.chmod(0o755)

            result = subprocess.run(
                ["bash", "launchd/codexbar-keychain/setup.sh"],
                cwd=Path(__file__).parents[1],
                env={**os.environ, "HOME": str(tmp), "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                input="\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("disabled", result.stdout.lower())
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
