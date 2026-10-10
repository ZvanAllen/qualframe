"""Verify and install a screened source archive, then exercise its synthetic app offline.

Requires an existing local wheelhouse for dependencies. Builds with the invoking
Python's already installed setuptools; the runtime venv is isolated. No downloads,
provider requests, environment credentials, or existing app processes are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import ProxyHandler, build_opener
import zipfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_environment(work: Path) -> dict[str, str]:
    permitted = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"}
    environment = {key: os.environ[key] for key in os.environ if key.upper() in permitted}
    home = work / "local-home"
    home.mkdir()
    environment.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home),
                        "LOCALAPPDATA": str(home), "TMP": str(home), "TEMP": str(home),
                        "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INDEX": "1",
                        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1",
                        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                        "PYTHONUTF8": "1"})
    return environment


def checked_run(command: list[str], *, cwd: Path, environment: dict[str, str], log: Path) -> None:
    with log.open("x", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=cwd, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Offline verification step failed; inspect {log.name}.")


def study_fingerprints(study: Path) -> dict[str, str]:
    paths = list((study / "data").rglob("*"))
    paths += list((study / "artifacts").rglob("*_artifact.json"))
    paths += list((study / "artifacts").rglob("run_manifest.json"))
    return {path.relative_to(study).as_posix(): sha(path) for path in paths if path.is_file()}


def worker(project: Path, ready: Path, port: int, launch_token: str) -> int:
    """Own one server; EOF or a stop message closes only this process's server."""
    from http.server import ThreadingHTTPServer
    import qualframe
    from qualframe.dashboard import DashboardApp, make_handler
    from qualframe.pipeline.project_runner import ProjectRunner

    installed = Path(qualframe.__file__).resolve()
    if not installed.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Runtime did not import the installed application wheel.")
    runner = ProjectRunner(project)
    if runner.project.provider.name != "mock" or runner.project.data_classification != "synthetic":
        raise RuntimeError("Release preflight accepts only its synthetic mock study.")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(DashboardApp(runner)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "port": server.server_port,
                                         "launch_token": launch_token,
                                         "installed_module": str(installed)}) + "\n", encoding="utf-8")
        temporary.replace(ready)
        sys.stdin.readline()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


def browser_smoke(python: Path, project: Path, work: Path, environment: dict[str, str],
                  iteration: int, port: int = 0) -> dict:
    ready = work / f"server-{iteration}.ready.json"
    log_path = work / f"server-{iteration}.log"
    frozen_helper = project.parents[2] / "scripts/release_preflight.py"
    launch_token = uuid.uuid4().hex
    args = [str(python), "-I", str(frozen_helper), "--worker", str(project),
            "--ready", str(ready), "--port", str(port), "--launch-token", launch_token]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = {}
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(args, cwd=work, env=environment, stdin=subprocess.PIPE,
                                   stdout=log, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        try:
            deadline = time.monotonic() + 30
            while not ready.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"Synthetic server failed to start; inspect {log_path.name}.")
                time.sleep(0.1)
            result = json.loads(ready.read_text(encoding="utf-8"))
            # Windows venv redirectors may launch a child with a different PID.
            if result.pop("launch_token", None) != launch_token:
                raise RuntimeError("Server readiness identity does not match the owned process.")
            result["launcher_pid"] = process.pid
            opener = build_opener(ProxyHandler({}))
            checked = []
            for path, expected in [("/", "Run coding"),
                                   ("/evidence?run_id=synthetic-review", 'value="accept"'),
                                   ("/compare", "Compare")]:
                with opener.open(f"http://127.0.0.1:{result['port']}{path}", timeout=10) as response:
                    page = response.read().decode("utf-8")
                    if response.status != 200 or expected not in page or response.headers.get("X-Content-Type-Options") != "nosniff":
                        raise RuntimeError("Synthetic application page failed its smoke check.")
                checked.append(path)
            result["checked_routes"] = checked
        finally:
            if process.poll() is None:
                try:
                    process.communicate("stop\n", timeout=15)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.communicate(timeout=10)
            result["graceful_stop"] = process.returncode == 0
    if not result.get("graceful_stop"):
        raise RuntimeError("Owned synthetic server did not stop cleanly.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--ready", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--launch-token", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not args.ready or not args.launch_token:
            parser.error("Worker readiness arguments are required.")
        return worker(args.worker, args.ready, args.port, args.launch_token)
    if not all([args.archive, args.wheelhouse, args.work_dir]):
        parser.error("Provide --archive, --wheelhouse and a new --work-dir.")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from package_public_release import public_files, verify_archive

    archive = args.archive.resolve()
    inventory = verify_archive(archive, (args.manifest or archive.with_suffix(".manifest.json")).resolve())
    wheelhouse = args.wheelhouse.resolve()
    if not wheelhouse.is_dir() or not list(wheelhouse.glob("*.whl")):
        raise ValueError("Provide an existing local dependency wheelhouse; no downloads are performed.")
    work = args.work_dir.resolve()
    if work.exists():
        raise FileExistsError("Choose a new work directory; previous trials are preserved.")
    if args.dry_run:
        print(json.dumps({"status": "archive_verified_installation_not_yet_tested", "archive_sha256": inventory["archive_sha256"],
                          "selected_files": inventory["file_count"], "will_create_isolated_venv": True,
                          "provider_calls": 0, "downloads": False}))
        return 0
    work.mkdir(parents=True)
    environment = clean_environment(work)
    receipt = {"kind": "qualframe_offline_release_preflight_v1", "status": "running",
               "platform": platform.platform(), "python_version": platform.python_version(),
               "archive_sha256": inventory["archive_sha256"], "file_count": inventory["file_count"],
               "isolated_runtime_venv": True, "downloads": False, "provider_calls": 0,
               "build_boundary": "Wheel built using invoking Python's existing setuptools; dependencies installed from local wheels into a new isolated runtime.",
               "macos_verified_by_this_run": sys.platform == "darwin"}
    receipt_path = work / "preflight_receipt.json"
    try:
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(work)  # All member names and hashes verified above.
        source = work / "qualframe"
        selected = {path.relative_to(source).as_posix() for path in public_files(source)}
        if selected != {row["path"] for row in inventory["files"]}:
            raise RuntimeError("Extracted source differs from the public selection.")
        dist = work / "wheels"
        dist.mkdir()
        checked_run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-cache-dir", "--no-deps",
                     "--no-build-isolation", "--wheel-dir", str(dist), str(source)],
                    cwd=work, environment=environment, log=work / "build.log")
        wheels = list(dist.glob("qualframe-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one application wheel.")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as packaged:
            required = {"qualframe/static/workspace.css", "qualframe/static/review.js"}
            if not required <= set(packaged.namelist()):
                raise RuntimeError("Application wheel is missing browser assets.")
        runtime = work / "venv"
        checked_run([sys.executable, "-m", "venv", str(runtime)], cwd=work,
                    environment=environment, log=work / "create-runtime.log")
        python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        checked_run([str(python), "-m", "pip", "install", "--no-index", "--no-cache-dir", "--find-links",
                     str(wheelhouse), str(wheel)], cwd=work, environment=environment, log=work / "install.log")
        checked_run([str(python), "-m", "pip", "check"], cwd=work, environment=environment, log=work / "dependencies.log")
        checked_run([str(python), "-m", "pip", "list", "--format=json"],
                    cwd=work, environment=environment, log=work / "installed-distributions.json")
        checked_run([str(python), "-I", "-c", "from qualframe.cli import app; app()", "--help"],
                    cwd=work, environment=environment, log=work / "cli.log")
        for entrypoint in ("qualframe", "qualframe-eval"):
            executable = python.parent / (entrypoint + ".exe" if os.name == "nt" else entrypoint)
            checked_run([str(executable), "--help"], cwd=work, environment=environment,
                        log=work / f"{entrypoint}-entrypoint.log")
        checked_run([str(python), str(source / "scripts/run_workspace_demo.py"), "--no-serve", "--study-id", "release-preflight"],
                    cwd=source, environment=environment, log=work / "workspace-demo.log")
        checked_run([str(python), str(source / "scripts/run_interview_demo.py"), "--run-id", "release-preflight"],
                    cwd=source, environment=environment, log=work / "cfir-demo.log")
        study = source / "studies/release-preflight"
        before = study_fingerprints(study)
        first = browser_smoke(python, study / "project.yaml", work, environment, 1)
        second = browser_smoke(python, study / "project.yaml", work, environment, 2, first["port"])
        if study_fingerprints(study) != before or list((study / "review_queue").rglob("actions.jsonl")):
            raise RuntimeError("Read-only app/restart checks changed source/output or human decisions.")
        receipt.update({"status": "passed", "wheel_sha256": sha(wheel), "wheel_file": wheel.name,
                        "installed_distributions": json.loads((work / "installed-distributions.json").read_text(encoding="utf-8")),
                        "server_trials": [first, second], "same_study_same_port_restart": True,
                        "sources_and_outputs_preserved": True, "human_actions_written": 0,
                        "installed_entrypoints": ["qualframe", "qualframe-eval"],
                        "workspace_demo": "2 synthetic transcripts and 4 valid evidence records",
                        "cfir_demo": "9 cached artifacts and 9 exports with seeded QA conflict"})
    except Exception as exc:
        receipt.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "receipt": str(receipt_path), "archive_sha256": inventory["archive_sha256"],
                      "runtime_isolated": True, "same_study_restart": True, "provider_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
