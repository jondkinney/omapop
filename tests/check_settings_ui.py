#!/usr/bin/env python3
"""Run the settings controls in Quickshell with a fake persistence service.

Quickshell's QML plugins are linked into qs, so a standalone qmltestrunner
cannot load them. QtTest runs inside this isolated, offscreen shell instead.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--ports", action="store_true", help="Test the port confirmation UI instead")
    args = parser.parse_args()
    fixture = Path(__file__).resolve().with_name("ports-ui.qml" if args.ports else "settings-ui.qml")
    shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
    with tempfile.TemporaryDirectory(prefix="omapop-settings-test-") as directory:
        root = Path(directory)
        imports = root / "imports"
        imports.mkdir()
        (imports / "qs").symlink_to(shell, target_is_directory=True)
        config = root / "shell.qml"
        config.write_text("""import QtQuick
import Quickshell
ShellRoot {
    FloatingWindow {
        visible: true
        implicitWidth: 460
        implicitHeight: 650
        Loader { anchors.fill: parent; source: %s }
    }
}
""" % json.dumps(fixture.as_uri()))
        env = os.environ.copy()
        env.pop("WAYLAND_DISPLAY", None)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_QPA_PLATFORMTHEME"] = "basic"
        env["QML_IMPORT_PATH"] = str(imports)
        if args.capture_dir:
            args.capture_dir.mkdir(parents=True, exist_ok=True)
            env["OMAPOP_SETTINGS_CAPTURE_DIR"] = str(args.capture_dir.resolve())
        try:
            result = subprocess.run(["qs", "--no-color", "-p", str(config)],
                                    env=env, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=30)
        except subprocess.TimeoutExpired as error:
            print((error.stdout or b'').decode('utf-8', 'replace'))
            print('Offscreen UI test timed out')
            return 1
        print(result.stdout, end="")
        marker = 'OMAPOP_PORT_TESTS' if args.ports else 'OMAPOP_SETTINGS_TESTS'
        match = re.search(marker + r" (\{[^\n]+\})", result.stdout)
        summary = json.loads(match[1]) if match else {}
        captured = not args.capture_dir or all(
            (args.capture_dir / name).is_file() and (args.capture_dir / name).stat().st_size > 0
            for name in (("confirmation.png",) if args.ports else ("selection.png", "advanced.png", "excluded-apps.png", "window-picker.png")))
        return 0 if result.returncode == 0 and summary.get("failed") == 0 and summary.get("passed", 0) >= (4 if args.ports else 20) and captured else 1


if __name__ == "__main__":
    raise SystemExit(main())
