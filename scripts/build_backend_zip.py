#!/usr/bin/env python
"""Create ``backend.zip`` for deployment to the central server.

The archive contains both the Django backend and the staff web panel:

    backend/
    website/

Usage (from the repository root)::

    python scripts/build_backend_zip.py
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIRS = [
    os.path.join(ROOT, "backend"),
    os.path.join(ROOT, "website"),
]
OUT = os.path.join(ROOT, "backend.zip")

EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_EXT = (".pyc", ".pyo", ".sqlite3", ".db", ".env", ".log")
EXCLUDE_FILES = {".env"}


def main():
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for source in SOURCE_DIRS:
            for root, dirs, files in os.walk(source):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for name in files:
                    if name in EXCLUDE_FILES or name.endswith(EXCLUDE_EXT):
                        continue
                    path = os.path.join(root, name)
                    arcname = os.path.relpath(path, ROOT)
                    zf.write(path, arcname)
                    count += 1
    size = os.path.getsize(OUT)
    print(f"Created {OUT}: {size / 1024 / 1024:.1f} MB ({count} files)")


if __name__ == "__main__":
    main()
