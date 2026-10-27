import os
import sys


def asset_path(filename):
    """
    Return absolute path for an asset file in both:
    - normal source run
    - PyInstaller packaged run
    """
    candidates = []

    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            candidates.append(os.path.join(mei, "assets", filename))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "assets", filename))
        candidates.append(os.path.join(exe_dir, "_internal", "assets", filename))
    else:
        app_dir = os.path.dirname(__file__)
        candidates.append(os.path.join(app_dir, "assets", filename))

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0] if candidates else filename
