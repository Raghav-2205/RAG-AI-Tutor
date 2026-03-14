from pathlib import Path
import sys


def ensure_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend").exists():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return parent
    raise RuntimeError("Project root not found")
