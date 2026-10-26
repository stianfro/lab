"""Test devbox settings generation without personal configuration or networking."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/devbox-sync-personal-config.sh"


class ClaudeSettingsTests(unittest.TestCase):
    def generate(self, settings):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            source = home / ".claude/settings.json"
            source.parent.mkdir(parents=True)
            original = json.dumps(settings, indent=2) + "\n"
            source.write_text(original)
            output = root / "generated.json"
            output.write_text("old output, not JSON\n")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in ("ssh", "rsync"):
                stub = bin_dir / name
                stub.write_text(
                    "#!/bin/sh\necho 'unexpected remote sync' >&2\nexit 99\n"
                )
                stub.chmod(0o700)
            environment = os.environ.copy()
            for key in ("DEVBOX_SYNC_CODEX_OUTPUT", "DEVBOX_SYNC_DRY_RUN"):
                environment.pop(key, None)
            environment.update(
                HOME=str(home),
                PATH=f"{bin_dir}{os.pathsep}{environment['PATH']}",
                DEVBOX_SYNC_CLAUDE_OUTPUT=str(output),
            )
            result = subprocess.run(
                ["bash", str(GENERATOR)],
                env=environment,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(source.read_text(), original)
            generated = json.loads(output.read_text())
            self.assertIsInstance(generated, dict)
            return generated

    def test_removes_only_legacy_mouse_flag(self):
        settings = {
            "env": {
                "CLAUDE_CODE_DISABLE_MOUSE": "1",
                "CLAUDE_CODE_DISABLE_MOUSE_CLICKS": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "EXAMPLE_SETTING": "unchanged",
            },
            "tui": "fullscreen",
        }
        generated = self.generate(settings)
        expected_env = dict(settings["env"])
        del expected_env["CLAUDE_CODE_DISABLE_MOUSE"]
        self.assertEqual(generated["env"], expected_env)
        self.assertEqual(generated["tui"], settings["tui"])

    def test_settings_without_env_are_supported(self):
        generated = self.generate({"model": "fixture-model"})
        self.assertEqual(generated.get("env", {}), {})
        self.assertEqual(generated["model"], "fixture-model")

    def test_hooks_remain_linux_safe(self):
        generated = self.generate(
            {"hooks": {"Stop": [{"hooks": [{"command": "afplay fixture.wav"}]}]}}
        )
        self.assertEqual(set(generated["hooks"]), {"SessionStart"})
        commands = [
            hook["command"]
            for group in generated["hooks"]["SessionStart"]
            for hook in group["hooks"]
        ]
        self.assertEqual(
            commands,
            [
                'bash "$HOME/.claude/hooks/minato-exec-engine.sh"',
                'bash "$HOME/.claude/hooks/herdr-agent-state.sh" session',
            ],
        )


if __name__ == "__main__":
    unittest.main()
