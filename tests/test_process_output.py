"""Exercise the actual Service.qml Task component in a separate, headless shell."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("quickshell"), "Quickshell is needed for process integration tests")
class ProcessOutputTests(unittest.TestCase):
    def run_task(self, stream, count, limit=16):
        service = (ROOT / "Service.qml").read_text()
        # Keep this harness on the production component, not a copy of its logic.
        component = service[service.index("    component Task:"):service.index("    property var activeTasks:")]
        producer = "import sys,time; sys.%s.write('x'*%d); sys.%s.flush(); time.sleep(20)" % (stream, count, stream)
        spec = {"command": ["/usr/bin/python3", "-I", "-c", producer], "limit": limit,
                "lineMode": True, "deadline": 3000}
        qml = '''import QtQuick
import Quickshell
import Quickshell.Io
import %s as OutputBuffer
ShellRoot {
    id: root
    property string home: "/"
    property var childEnv: ({})
%s
    Task {
        spec: (%s)
        property double began: Date.now()
        Component.onCompleted: start()
        onFinished: function (result) {
            result.elapsed = Date.now() - began
            console.log("TASK_RESULT=" + JSON.stringify(result))
            Qt.quit()
        }
    }
}''' % (json.dumps((ROOT / "OutputBuffer.js").as_uri()), component, json.dumps(spec))
        with tempfile.TemporaryDirectory(prefix="omapop-process-test-") as tmp:
            path = Path(tmp) / "shell.qml"
            path.write_text(qml)
            proc = subprocess.run([shutil.which("quickshell"), "--no-color", "-p", str(path)],
                                  env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        marker = "TASK_RESULT="
        lines = [line.split(marker, 1)[1] for line in proc.stdout.splitlines() if marker in line]
        self.assertEqual(len(lines), 1, proc.stdout)
        return json.loads(lines[0])

    def test_newline_free_limit_plus_one_producer_is_killed_immediately(self):
        result = self.run_task("stdout", 17)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["timedOut"])
        self.assertLess(result["elapsed"], 1500)
        self.assertFalse(result["ok"])

    def test_stderr_limit_plus_one_producer_is_also_killed(self):
        result = self.run_task("stderr", 16385)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["timedOut"])
        self.assertLess(result["elapsed"], 1500)


if __name__ == "__main__":
    unittest.main()
