#!/usr/bin/env python3
"""Check the real plugin QML with Quickshell's Wayland backend.

Offscreen Quickshell has no PanelWindow backend, so control-only tests cannot
catch every popup load failure. This check needs a Wayland session but shows no
windows, installs no input hooks, and starts no Omapop service processes.
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
    parser.add_argument('--plugin-dir', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if not os.environ.get('WAYLAND_DISPLAY'):
        parser.error('Run this check in a Wayland session; the offscreen backend cannot load PanelWindow')
    plugin = args.plugin_dir.resolve()
    files = [str((plugin / name).as_uri()) for name in ('Popup.qml', 'Service.qml', 'BarWidget.qml')]
    shell = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell'
    with tempfile.TemporaryDirectory(prefix='omapop-plugin-load-') as directory:
        root = Path(directory)
        imports = root / 'imports'
        imports.mkdir()
        (imports / 'qs').symlink_to(shell, target_is_directory=True)
        config = root / 'shell.qml'
        config.write_text('''import QtQuick
import Quickshell
ShellRoot {
    Component.onCompleted: Qt.callLater(checkComponents)
    function checkComponents() {
        var files = %s
        var passed = 0
        var failures = []
        for (var i = 0; i < files.length; i++) {
            var component = Qt.createComponent(files[i])
            if (component.status === Component.Ready) passed++
            else failures.push(component.errorString() || (files[i] + ": load did not complete"))
            component.destroy()
        }
        console.log("OMAPOP_LOAD_TESTS " + JSON.stringify({passed: passed, failures: failures}))
        Qt.quit()
    }
}
''' % json.dumps(files))
        env = dict(os.environ, QT_QPA_PLATFORM='wayland', QT_QPA_PLATFORMTHEME='basic',
                   QT_QUICK_BACKEND='software', QML_IMPORT_PATH=str(imports))
        try:
            result = subprocess.run(['qs', '--no-color', '-p', str(config)], env=env,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        except subprocess.TimeoutExpired as error:
            print((error.stdout or b'').decode('utf-8', 'replace'))
            print('Plugin QML load check timed out')
            return 1
        print(result.stdout, end='')
        match = re.search(r'OMAPOP_LOAD_TESTS (\{[^\n]+\})', result.stdout)
        report = json.loads(match[1]) if match else {}
        return 0 if result.returncode == 0 and report.get('passed') == len(files) and report.get('failures') == [] else 1


if __name__ == '__main__':
    raise SystemExit(main())
