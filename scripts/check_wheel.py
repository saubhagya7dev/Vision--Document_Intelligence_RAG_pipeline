"""Smoke-test our built wheel outside the source tree, with disposable storage."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--output", type=Path, default=Path("Docs/phase7-wheel.json"))
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    code = """
import json
from pathlib import Path
from fastapi.testclient import TestClient
import vision_rag
from vision_rag.api.main import app
assert Path(vision_rag.__file__).resolve().is_relative_to(Path.cwd() / "installed")
with TestClient(app) as client:
    assert client.get('/health').json() == {'status':'ok'}
    assert client.get('/api/v1/documents').status_code == 401
    state = client.get('/api/v1/session').json()
    assert state == {'required':True,'authenticated':False}
    assert client.get('/').status_code == 200
    assert client.get('/static/session.js').status_code == 200
    assert client.get('/static/styles.css').status_code == 200
    token = 'public-wheel-fixture-token-1234567890'
    assert client.post('/api/v1/session',json={'token':token}).status_code == 200
    assert client.get('/api/v1/documents').status_code == 200
    assert client.get('/openapi.json').status_code == 200
    client.delete('/api/v1/session')
    assert client.get('/api/v1/documents').status_code == 401
print(json.dumps({'status':'passed','isolated_import':True,'auth_and_static_routes':True}))
"""
    with tempfile.TemporaryDirectory(prefix="vision-wheel-") as folder:
        root = Path(folder).resolve()
        installed = root / "installed"
        installed.mkdir()
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if not (installed / name).resolve().is_relative_to(installed):
                    raise ValueError("Wheel path escapes its target")
                if any(p in (".env", "data", ".git") for p in Path(name).parts):
                    raise ValueError("Wheel contains private runtime files")
            archive.extractall(installed)
        env = {
            **os.environ,
            "PYTHONPATH": str(installed),
            "DATA_DIR": str(root / "library"),
            "ACCESS_TOKEN": "public-wheel-fixture-token-1234567890",
            "DEPLOYMENT_PROFILE": "authenticated",
            "ALLOWED_HOSTS": '["testserver"]',
            "BIND_HOST": "127.0.0.1",
            "QDRANT_MODE": "local",
            "GOOGLE_API_KEY": "",
            "INGESTION_WORKER_ENABLED": "false",
            "IMPORT_LEGACY_PDFS": "false",
            "MODEL_WARMUP": "false",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        report = {
            "status": "passed" if result.returncode == 0 else "failed",
            "wheel": wheel.name,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "returncode": result.returncode,
            "scope": "Wheel imports/static/API/session smoke in fresh data directory; "
            "dependencies supplied by current .venv; not a fresh dependency install",
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if result.returncode:
            print(result.stdout)
            print(result.stderr)
            raise SystemExit(result.returncode)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
