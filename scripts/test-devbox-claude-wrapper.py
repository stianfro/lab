#!/usr/bin/env python3
"""Test the targeted Claude wrapper migration without running Claude."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "ansible/devbox/roles/shell/tasks/claude-wrapper.yaml"
ORIGINAL = 'function claude; command "$REAL_CLAUDE" $argv; end; cla $argv'
FIXED = 'function claude; exec "$REAL_CLAUDE" $argv; end; cla $argv'


class ClaudeWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tasks = json.loads(
            subprocess.check_output(["yq", "-o=json", ".", str(TASKS)], text=True)
        )
        rules = [
            task["ansible.builtin.replace"]
            for task in tasks
            if "ansible.builtin.replace" in task
        ]
        if len(rules) != 1:
            raise AssertionError(f"Expected one replacement rule, got {len(rules)}")
        cls.rule = rules[0]
        cls.fish = shutil.which("fish")
        if cls.fish is None:
            raise AssertionError("fish is required for the wrapper regression tests")

    def patch(self, source):
        return re.subn(self.rule["regexp"], self.rule["replace"], source)

    def test_targeted_replacement_is_idempotent(self):
        patched, count = self.patch(ORIGINAL)
        self.assertEqual((patched, count), (FIXED, 1))
        self.assertEqual(self.patch(patched), (FIXED, 0))

    def test_unrelated_wrappers_are_unchanged(self):
        for source in (
            'exec "$HOME/.local/bin/claude" "$@"',
            'function claude; command "$OTHER_CLAUDE" $argv; end; cla $argv',
            'function claude; command "$REAL_CLAUDE" $argv; end; other $argv',
        ):
            with self.subTest(source=source):
                self.assertEqual(self.patch(source), (source, 0))

    def run_wrapper(self, patched):
        arguments = ["--model", "model with spaces", "", "literal;$argument"]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            real = directory / "real-claude"
            real.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "print(json.dumps({'pid': os.getpid(), 'args': sys.argv[1:], "
                "'env': os.environ.get('CLAUDE_WRAPPER_TEST_ENV')}))\n"
                "sys.exit(23)\n"
            )
            real.chmod(0o700)
            body = (
                "function cla\n"
                "    set -lx CLAUDE_WRAPPER_TEST_ENV 'scoped value'\n"
                "    claude $argv\n"
                "end\n"
                f"{ORIGINAL}\n"
            )
            if patched:
                body, count = self.patch(body)
                self.assertEqual(count, 1)
            wrapper = directory / "wrapper.bash"
            wrapper.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                f"exec {shlex.quote(self.fish)} --no-config -c "
                f'{shlex.quote(body)} -- "$@"\n'
            )
            environment = os.environ.copy()
            environment["REAL_CLAUDE"] = str(real)
            environment.pop("CLAUDE_WRAPPER_TEST_ENV", None)
            with subprocess.Popen(
                ["/bin/bash", str(wrapper), *arguments],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 23, stderr)
                result = json.loads(stdout)
                self.assertEqual(result["args"], arguments)
                self.assertEqual(result["env"], "scoped value")
                return process.pid, result["pid"]

    def test_exec_preserves_pid_arguments_environment_and_exit_status(self):
        wrapper_pid, real_pid = self.run_wrapper(patched=True)
        self.assertEqual(wrapper_pid, real_pid)

    def test_original_wrapper_keeps_an_extra_shell_process(self):
        wrapper_pid, real_pid = self.run_wrapper(patched=False)
        self.assertNotEqual(wrapper_pid, real_pid)


if __name__ == "__main__":
    unittest.main()
