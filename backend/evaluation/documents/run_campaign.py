"""STEP 20 dynamic-KB evaluation campaign (evaluation-only, live server driver).

Run:  python -m evaluation.documents.run_campaign [--base-url ...] [--run-id ...]
Manages its own backend server subprocess (start/stop/restart) so restart
persistence is genuinely exercised. Never touches the static collection.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = r"D:\CMTI\.venv\Scripts\python.exe"
STATIC_COLLECTION_EXPECTED = 2193


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Http:
    def __init__(self, base: str) -> None:
        self.base = base

    def call(self, method: str, path: str, body=None, ctype: str | None = None,
             filename: str = "upload.pdf", timeout: int = 120):
        data = None
        headers: dict[str, str] = {}
        if body is not None:
            if ctype == "multipart":
                boundary = "EVALBOUNDARY98765"
                data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                        f"filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n").encode() \
                    + body + f"\r\n--{boundary}--\r\n".encode()
                headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        try:
            request = urllib.request.Request(self.base + path, data=data,
                                             headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode()
                try:
                    payload: object = json.loads(raw)
                except ValueError:
                    payload = raw[:500]
                return response.status, payload, (time.perf_counter() - started) * 1000.0
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()[:500], (time.perf_counter() - started) * 1000.0


def static_count_direct() -> int:
    """Count static vectors with the server DOWN (avoids the single-client rule)."""

    code = (
        "from app.rag.vector_store import VectorStore;"
        "from app.core.config import Settings;"
        "s=Settings(_env_file=None);"
        "vs=VectorStore(s.vector_store_path,s.rag_collection_name);"
        "print(vs.point_count());vs.close()"
    )
    out = subprocess.run([VENV_PYTHON, "-c", code], cwd=str(BACKEND_ROOT),
                         capture_output=True, text=True, timeout=300)
    return int(out.stdout.strip().splitlines()[-1])


def dynamic_counts_direct() -> dict[str, int]:
    """Registry rows / vectors / originals with the server DOWN."""

    code = (
        "import pathlib,sqlite3;"
        "root=pathlib.Path(r'D:\\CMTI\\data\\documents');"
        "db=root/'registry'/'documents.db';"
        "rows=sqlite3.connect(str(db)).execute('SELECT COUNT(*) FROM documents').fetchone()[0] if db.exists() else 0;"
        "orig=len(list((root/'originals').glob('*'))) if (root/'originals').exists() else 0;"
        "print(f'{rows} {orig}')"
    )
    out = subprocess.run([VENV_PYTHON, "-c", code], capture_output=True,
                         text=True, timeout=120)
    rows, orig = (out.stdout.strip().split() + ["0", "0"])[:2]
    return {"registry_rows": int(rows), "originals": int(orig)}


def dynamic_vectors_direct() -> int:
    code = (
        "from app.rag.vector_store import VectorStore;"
        "from app.core.config import Settings;"
        "s=Settings(_env_file=None);"
        "vs=VectorStore(s.document_storage_root/'vectors',s.document_dynamic_collection);"
        "print(vs.point_count());vs.close()"
    )
    out = subprocess.run([VENV_PYTHON, "-c", code], cwd=str(BACKEND_ROOT),
                         capture_output=True, text=True, timeout=300)
    text = out.stdout.strip()
    return int(text.splitlines()[-1]) if text else 0


class Server:
    def __init__(self, port: int, extra_env: dict[str, str] | None = None) -> None:
        self.port = port
        self.extra_env = extra_env or {}
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        import os

        env = {k: v for k, v in os.environ.items()
               if k not in ("TYPESAFE_API_KEY", "GEMINI_API_KEY")}
        env.update(self.extra_env)
        self.process = subprocess.Popen(
            [VENV_PYTHON, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(BACKEND_ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        http = Http(f"http://127.0.0.1:{self.port}")
        for _ in range(90):
            time.sleep(1)
            try:
                status, _, _ = http.call("GET", "/health", timeout=5)
                if status == 200:
                    return
            except Exception:
                pass
        raise RuntimeError(f"server on {self.port} did not become ready")

    def stop(self) -> None:
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=30)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STEP 20 dynamic-KB campaign")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-root", default=r"D:\CMTI\reports\evaluation\documents")
    args = parser.parse_args(argv)
    run_id = args.run_id or (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_dynamickb")
    out = Path(args.out_root) / run_id
    from evaluation.documents.campaign import run_campaign, write_reports

    result = run_campaign(port=args.port, out_dir=out)
    paths = write_reports(out, result)
    print(f"uploads={len(result['uploads'])} retrievals={len(result['retrievals'])} "
          f"deletions={len(result['deletions'])} failures={len(result['failures'])}")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    return 0 if not result.get("critical_failures") else 1


if __name__ == "__main__":
    raise SystemExit(main())
