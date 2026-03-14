import os
import re
import sys
import warnings
from pathlib import Path

import uvicorn


warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def _configure_console() -> None:
    """Avoid Windows cp1252 crashes when logs contain non-ASCII output."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _load_env_file(env_path: Path) -> None:
    """
    Load .env values into the process environment before model imports.
    Third-party libraries such as Hugging Face read these flags directly
    from os.environ, so pydantic settings alone are not enough.
    """
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        if (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value).strip()

        os.environ[key] = value


if __name__ == "__main__":
    _configure_console()

    current_dir = Path(__file__).resolve().parent
    sys.path.append(str(current_dir))
    _load_env_file(current_dir / ".env")

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("RUN_PORT", "8002"))

    print("------------------------------------------------")
    print("Initializing RAG AI Tutor Server...")
    print(f"Project Root: {current_dir}")
    print(f"Server URL: http://{host}:{port}")
    print("------------------------------------------------")

    try:
        from backend.main import app  # noqa: F401

        print("Backend app imported successfully.")
        print("Press Ctrl+C to stop.")

        uvicorn.run(
            "backend.main:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )
    except ImportError as exc:
        print(f"\nCritical import error: {exc}")
        print("Did you rename a file or folder?")
        raise
    except Exception as exc:
        print(f"\nServer crashed: {exc}")
        raise
