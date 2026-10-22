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
    parser.add_argument('--theme-colors', action='store_true',
                        help='Instantiate themed components and check their colors against Omarchy')
    args = parser.parse_args()
    if not os.environ.get('WAYLAND_DISPLAY'):
        parser.error('Run this check in a Wayland session; the offscreen backend cannot load PanelWindow')
    plugin = args.plugin_dir.resolve()
    names = ('Popup.qml', 'BarWidget.qml', 'Settings.qml', 'ExcludedApps.qml',
             'ShortcutRecorder.qml', 'ConfirmationText.qml') if args.theme_colors else (
                 'Popup.qml', 'Service.qml', 'BarWidget.qml')
    files = [str((plugin / name).as_uri()) for name in names]
    shell = Path(os.environ.get('OMARCHY_PATH', '/usr/share/omarchy')) / 'shell'
    with tempfile.TemporaryDirectory(prefix='omapop-plugin-load-') as directory:
        root = Path(directory)
        imports = root / 'imports'
        imports.mkdir()
        (imports / 'qs').symlink_to(shell, target_is_directory=True)
        config = root / 'shell.qml'
        config.write_text('''import QtQuick
import Quickshell
import qs.Commons as OmarchyTheme
ShellRoot {
    id: testRoot
    Component.onCompleted: Qt.callLater(checkComponents)
    function checkColors(file, component, failures) {
        var object = component.createObject(testRoot)
        if (!object) {
            failures.push(file + ": could not instantiate component")
            return false
        }
        var name = file.slice(file.lastIndexOf("/") + 1)
        var fg = OmarchyTheme.Color.popups.text
        var expected
        if (name === "Popup.qml") {
            expected = { bg: OmarchyTheme.Color.popups.background, fg: fg,
                borderColor: OmarchyTheme.Color.popups.border,
                hoverFill: OmarchyTheme.Style.hoverFillFor(fg, OmarchyTheme.Color.accent, OmarchyTheme.Color.urgent) }
        } else if (name === "ConfirmationText.qml") {
            expected = { foreground: fg }
        } else {
            expected = { secondaryText: Qt.rgba(fg.r, fg.g, fg.b, 0.68 * (name === "BarWidget.qml" ? fg.a : 1)) }
        }
        var passed = true
        for (var property in expected) {
            if (!Qt.colorEqual(object[property], expected[property])) {
                failures.push(name + "." + property + ": expected " + expected[property] + ", got " + object[property])
                passed = false
            }
        }
        return passed
    }
    function checkComponents() {
        var files = %s
        var themeColors = %s
        var passed = 0
        var failures = []
        for (var i = 0; i < files.length; i++) {
            var component = Qt.createComponent(files[i])
            if (component.status === Component.Ready) {
                if (!themeColors || checkColors(files[i], component, failures)) passed++
            }
            else failures.push(component.errorString() || (files[i] + ": load did not complete"))
            component.destroy()
        }
        console.log("OMAPOP_LOAD_TESTS " + JSON.stringify({passed: passed, failures: failures}))
        Qt.quit()
    }
}
''' % (json.dumps(files), json.dumps(args.theme_colors)))
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
