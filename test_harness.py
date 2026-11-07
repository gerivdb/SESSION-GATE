#!/usr/bin/env python3
# =============================================================================
# test_harness.py — 9 tests du harness ENV6
#
# Chaque test crée son propre HARNESS_HOME temporaire, invoque harness.py
# via subprocess, et affiche une seule ligne : PASS <nom> ou FAIL <nom>: <raison>.
# Aucun import depuis SKILLS/, citizen_*, api_inspector, bridge_generator.
# Aucune dépendance à D:\DO\WEB\TOOLS\L4-TOOLS\ ni à RAGX\.venv\.
# =============================================================================
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HARNESS_PATH = Path(__file__).resolve().parent / "harness.py"
PYTHON = sys.executable


def _run(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, str(HARNESS_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _mk_git_repo(base: Path) -> str:
    """Crée un repo git avec un fichier initial, retourne son chemin."""
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("initial")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=repo, capture_output=True, check=True
    )
    return str(repo)


def _mk_artifacts(base: Path, entries: list) -> str:
    p = Path(base) / "artifacts.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return str(p)


TESTS = []


def _test(name: str):
    def decorator(fn):
        TESTS.append((name, fn))
        return fn
    return decorator


@_test("test_identity_lifecycle")
def test_identity_lifecycle() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    r = _run("init", env=env)
    if r.returncode != 0:
        return False, f"init failed: {r.stderr}"
    r = _run("new-conv", "--alias", "A", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    data = json.loads(r.stdout)
    session = data.get("session")
    shard_id = data.get("shard_id")
    if not session or not shard_id:
        return False, "missing session/shard_id in new-conv output"
    r = _run("list", env=env)
    if r.returncode != 0 or "A" not in r.stdout:
        return False, "list does not contain alias A"
    r = _run("invoke", "--alias", "A", env=env)
    if r.returncode != 0 or shard_id not in r.stdout:
        return False, "invoke does not print shard_id"
    r = _run("stop", "--alias", "A", env=env)
    if r.returncode != 0:
        return False, f"stop failed: {r.stderr}"
    return True, ""


@_test("test_session_lock_and_seal")
def test_session_lock_and_seal() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "B", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "B", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    # double observe → lock
    r2 = _run(
        "observe", "--session", sid, "--alias", "B", "--objective", "t2",
        "--scope-repos", repo, env=env,
    )
    if r2.returncode == 0:
        return False, "second observe should be locked"
    # seal sans gate → fail
    r3 = _run("seal", "--session", sid, env=env)
    if r3.returncode == 0:
        return False, "seal without gate should fail"
    return True, ""


@_test("test_gate_and_seal_end_to_end")
def test_gate_and_seal_end_to_end() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "C", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "C", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    arts = {"artifacts": [{"path": "a.py", "owner": "C", "dest": "track", "cmd": "git add a.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode != 0:
        return False, f"gate closure failed: {r.stderr}"
    data = json.loads(r.stdout)
    if data.get("gate") != "PASS":
        return False, f"gate not PASS: {data}"
    r = _run("seal", "--session", sid, env=env)
    if r.returncode != 0:
        return False, f"seal failed: {r.stderr}"
    data = json.loads(r.stdout)
    if not data.get("ok") or "wal" not in data:
        return False, f"seal did not return wal: {data}"
    return True, ""


@_test("test_gate_fails_dirty_tree")
def test_gate_fails_dirty_tree() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "D", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "D", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    arts = {"artifacts": [{"path": "x.py", "owner": "D", "dest": "track", "cmd": "git add x.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    (Path(repo) / "junk.log").write_text("leak")
    r = _run("gate", "--session", sid, "--intent", "wip", env=env)
    if r.returncode == 0:
        return False, "wip should fail on leak"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode == 0:
        return False, "closure should fail with leak present"
    return True, ""


@_test("test_triage_required_before_closure")
def test_triage_required_before_closure() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "E", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "E", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode == 0:
        return False, "closure without triage should fail"
    data = json.loads(r.stdout)
    if not any(i["reason"] == "triage_missing" for i in data.get("issues", [])):
        return False, "expected triage_missing issue"
    arts = {"artifacts": [{"path": "a.py", "owner": "E", "dest": "track", "cmd": "git add a.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode != 0:
        return False, f"closure after triage failed: {r.stderr}"
    return True, ""


@_test("test_wip_leak_blocks_closure_until_resolved")
def test_wip_leak_blocks_closure_until_resolved() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "F", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "F", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    arts = {"artifacts": [{"path": "x.py", "owner": "F", "dest": "track", "cmd": "git add x.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    (Path(repo) / "junk.log").write_text("leak")
    r = _run("gate", "--session", sid, "--intent", "wip", env=env)
    if r.returncode == 0:
        return False, "wip should fail on leak"
    data = json.loads(r.stdout)
    if not any(i["reason"] == "leak_detected" for i in data.get("issues", [])):
        return False, "expected leak_detected issue"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode == 0:
        return False, "closure should fail with unresolved wip"
    data = json.loads(r.stdout)
    if not any(i["reason"] == "wip_unresolved" for i in data.get("issues", [])):
        return False, "expected wip_unresolved issue"
    (Path(repo) / "junk.log").unlink()
    r = _run("gate", "--session", sid, "--intent", "wip", env=env)
    if r.returncode != 0:
        return False, f"wip after cleanup failed: {r.stderr}"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode != 0:
        return False, f"closure after wip resolve failed: {r.stderr}"
    return True, ""


@_test("test_wip_baseline_deletion")
def test_wip_baseline_deletion() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    (Path(repo) / "keep.py").write_text("keep")
    subprocess.run(["git", "add", "keep.py"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "keep"], cwd=repo, capture_output=True, check=True
    )
    r = _run("new-conv", "--alias", "G", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "G", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    (Path(repo) / "keep.py").unlink()
    r = _run("gate", "--session", sid, "--intent", "wip", env=env)
    if r.returncode == 0:
        return False, "wip should fail on baseline deletion"
    data = json.loads(r.stdout)
    if not any(i["reason"] == "unexpected_deletes" for i in data.get("issues", [])):
        return False, "expected unexpected_deletes issue"
    return True, ""


@_test("test_hygiene_resolves_wip_failures")
def test_hygiene_resolves_wip_failures() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "H", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "H", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    arts = {"artifacts": [{"path": "x.py", "owner": "H", "dest": "track", "cmd": "git add x.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    (Path(repo) / "junk.log").write_text("leak")
    r = _run("gate", "--session", sid, "--intent", "wip", env=env)
    if r.returncode == 0:
        return False, "wip should fail on leak"
    (Path(repo) / "junk.log").unlink()
    r = _run("gate", "--session", sid, "--intent", "hygiene", env=env)
    if r.returncode != 0:
        return False, f"hygiene after cleanup failed: {r.stderr}"
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode != 0:
        return False, f"closure after hygiene failed: {r.stderr}"
    return True, ""


@_test("test_abandon_releases_lock")
def test_abandon_releases_lock() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "I", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "I", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    r = _run("abandon", "--session", sid, env=env)
    if r.returncode != 0:
        return False, f"abandon failed: {r.stderr}"
    r = _run(
        "observe", "--session", sid, "--alias", "I", "--objective", "u",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"re-observe after abandon failed: {r.stderr}"
    return True, ""


@_test("test_gate_closure_detects_modified")
def test_gate_closure_detects_modified() -> tuple[bool, str]:
    home = Path(tempfile.mkdtemp())
    env = dict(os.environ, HARNESS_HOME=str(home))
    repo = _mk_git_repo(home)
    r = _run("new-conv", "--alias", "J", env=env)
    if r.returncode != 0:
        return False, f"new-conv failed: {r.stderr}"
    sid = json.loads(r.stdout)["session"]
    r = _run(
        "observe", "--session", sid, "--alias", "J", "--objective", "t",
        "--scope-repos", repo, env=env,
    )
    if r.returncode != 0:
        return False, f"observe failed: {r.stderr}"
    arts = {"artifacts": [{"path": "a.py", "owner": "J", "dest": "track", "cmd": "git add a.py"}]}
    arts_path = _mk_artifacts(home, arts["artifacts"])
    r = _run("triage", "--session", sid, "--artifacts", arts_path, env=env)
    if r.returncode != 0:
        return False, f"triage failed: {r.stderr}"
    # MODIFIER un fichier tracké existant (pas un nouveau fichier)
    (Path(repo) / "README.md").write_text("modified content")
    r = _run("gate", "--session", sid, "--intent", "closure", env=env)
    if r.returncode == 0:
        return False, "closure should FAIL on modified tracked file"
    data = json.loads(r.stdout)
    if not any(i["reason"] == "tree_dirty" for i in data.get("issues", [])):
        return False, f"expected tree_dirty issue, got: {data}"
    return True, ""


def main() -> int:
    results = []
    fails = 0
    for name, fn in TESTS:
        try:
            ok, reason = fn()
            if ok:
                print(f"PASS {name}")
            else:
                print(f"FAIL {name}: {reason}")
                fails += 1
        except Exception as e:
            print(f"FAIL {name}: {e}")
            fails += 1
    return fails


if __name__ == "__main__":
    sys.exit(main())
