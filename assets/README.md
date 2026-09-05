# Listing preview

`preview.qml` combines a code-drawn example of the selection bar, using Omapop's
actual icon components, with `extensions-panel.png`, a scoped capture of the
running extensions panel. The screenshot includes no surrounding desktop,
private documents, or account details. The composition is an illustration plus
a real UI capture, not a screenshot of a single application window.

To regenerate the root `preview.jpg`, with PySide6 installed for development:

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=opengl python3 assets/render-preview.py
```

These assets are not loaded by the plugin at runtime. Omapop is independent of
PopClip; third-party extension names and marks in the UI identify those extensions.
