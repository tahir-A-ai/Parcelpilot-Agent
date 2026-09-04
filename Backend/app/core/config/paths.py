"""
Shared filesystem path constants for the ParcelPilot backend.

Centralises path resolution so scripts and tools do not each re-derive
the Backend/ root directory from __file__. Import BACKEND_DIR wherever
an absolute filesystem path is needed at runtime.
"""

from pathlib import Path

# Absolute path to the Backend/ directory.
# This file lives at: Backend/app/core/config/paths.py
# So parent*4 → Backend/  (config → core → app → Backend)
BACKEND_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
