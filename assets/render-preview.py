#!/usr/bin/python3
"""Render the code-native listing composition; development-only PySide6 dependency."""
from pathlib import Path
import sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

root = Path(__file__).resolve().parent.parent
QQuickWindow.setGraphicsApi(QSGRendererInterface.OpenGL)
app = QGuiApplication(sys.argv)
view = QQuickView()
view.setSource(QUrl.fromLocalFile(str(root / "assets" / "preview.qml")))
if view.status() == QQuickView.Error:
    raise SystemExit(1)
view.show()


def capture():
    rendered = view.grabWindow()
    saved = not rendered.isNull() and rendered.save(str(root / "preview.jpg"), "JPEG", 95)
    app.exit(0 if saved else 1)


QTimer.singleShot(1500, capture)
QTimer.singleShot(10000, lambda: app.exit(2))
raise SystemExit(app.exec())
