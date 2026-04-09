import os
import re
import subprocess
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


def _ensure_email_validator() -> None:
    """Install the optional Pydantic email dependency if it is missing."""
    try:
        import email_validator  # noqa: F401
        return
    except ImportError:
        pass

    package_name = "email-validator"
    install_cmd = [sys.executable, "-m", "pip", "install", package_name]

    print("Missing dependency detected: email-validator")
    print("Installing it automatically so EmailStr-based models can load...")

    try:
        subprocess.run(install_cmd, check=True)
        import email_validator  # noqa: F401
        print("Dependency installed successfully.")
    except Exception as exc:
        print("\nCritical dependency install error: email-validator could not be installed automatically.")
        print(f"Installer command: {' '.join(install_cmd)}")
        print(f"Underlying error: {exc}")
        print("Manual fallback:")
        print(f"  {' '.join(install_cmd)}")
        print("Note: package-index/network access may be required in this environment.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    _configure_console()

    current_dir = Path(__file__).resolve().parent
    sys.path.append(str(current_dir))
    _load_env_file(current_dir / ".env")
    _ensure_email_validator()

    host = os.getenv("API_HOST", "127.0.0.1")
    port_raw = os.getenv("RUN_PORT", "8003")
    port = int(port_raw)
    port_source = "RUN_PORT override" if "RUN_PORT" in os.environ else "default"

    print("------------------------------------------------")
    print("Initializing RAG AI Tutor Server...")
    print(f"Project Root: {current_dir}")
    print(f"Server URL: http://{host}:{port}")
    print(f"Port Source: {port_source} ({port_raw})")
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
