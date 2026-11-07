#!/usr/bin/env python3
# =============================================================================
# harness.py — Harness de discipline ENV6 (4 verbes + 1 événement)
#
# observe → triage → gate → seal, avec événement escalate latéral.
# État de session dans $HARNESS_HOME/harness/session-<uuid>.json
# Lock via atomic mkdir (portable Windows/POSIX, pas de flock).
# Stateless par session : état effacé après seal ou abandon (TTL 24h sinon).
#
# Verbes : init, new-conv, list, rename, stop, invoke, observe, triage,
#          gate, seal, abandon.
# Événement : escalate (écrit sur stderr, jamais un verbe CLI).
# =============================================================================
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_BASE = Path(os.environ.get("HARNESS_HOME", tempfile.gettempdir()))
TMP_DIR = _BASE / "harness"
TMP_DIR.mkdir(parents=True, exist_ok=True)

WHITELIST_EXT = {
    ".py", ".md", ".json", ".jsonl", ".ps1", ".zig", ".toml", ".yaml", ".yml", ".txt",
}
LEAK_PATTERNS = ["*.bak", "*.log", "*.stackdump", "*.tmp", "*~", "*.orig"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_path(session: str) -> Path:
    return TMP_DIR / f"session-{session}.json"


def lock_path(session: str) -> Path:
    return TMP_DIR / f"session-{session}.lock"


def conv_path(alias: str) -> Path:
    return TMP_DIR / f"conv-{alias}.json"


def ensure_home() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: List[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _snapshot_repo(repo: str) -> Optional[List[str]]:
    """Set des fichiers présents sur disque (tracked + untracked non-ignored)."""
    rc, out, _ = _run(["git", "-C", repo, "ls-files", "-co", "--exclude-standard"])
    if rc != 0:
        return None
    candidates = out.splitlines() if out else []
    root = Path(repo)
    return [f for f in candidates if (root / f).exists()]


def _is_leak(path: str) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pat) for pat in LEAK_PATTERNS)


def _wip_check(repo: str, baseline: Optional[List[str]]) -> tuple[List[tuple[str, str]], dict]:
    """Compare l'état disque courant au baseline observe.
    Modification d'un fichier existant : autorisée (c'est du WIP).
    Ajout, suppression, ou leak : refusés."""
    if baseline is None:
        return [("no_baseline", repo)], {}
    current = _snapshot_repo(repo)
    if current is None:
        return [("git_failed", f"snapshot_failed:{repo}")], {}
    baseline_set = set(baseline)
    current_set = set(current)
    added = current_set - baseline_set
    deleted = baseline_set - current_set

    issues: List[tuple[str, str]] = []
    details: dict = {}

    leaks = sorted(p for p in added if _is_leak(p))
    if leaks:
        issues.append(("leak_detected", repo))
        details["leaks"] = leaks

    bad_ext = sorted(
        p for p in added
        if Path(p).suffix.lower() not in WHITELIST_EXT and not _is_leak(p)
    )
    if bad_ext:
        issues.append(("bad_extension", repo))
        details["bad_ext"] = bad_ext

    if deleted:
        issues.append(("unexpected_deletes", repo))
        details["deleted"] = sorted(deleted)

    return issues, details


# ---------------------------------------------------------------------------
# Verbes
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    ensure_home()
    print(json.dumps({"ok": True, "home": str(TMP_DIR)}))
    return 0


def cmd_new_conv(args: argparse.Namespace) -> int:
    ensure_home()
    alias = args.alias
    session = str(uuid.uuid4())
    shard_id = f"shard-{hashlib.sha256(session.encode()).hexdigest()[:8]}"
    conv = {
        "alias": alias,
        "session": session,
        "shard_id": shard_id,
        "created": now_iso(),
        "status": "active",
    }
    conv_path(alias).write_text(json.dumps(conv, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "session": session, "alias": alias, "shard_id": shard_id}))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    ensure_home()
    convs: List[dict] = []
    for p in TMP_DIR.glob("conv-*.json"):
        try:
            convs.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    print(json.dumps({"ok": True, "conversations": convs}, indent=2))
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    ensure_home()
    old = conv_path(args.alias)
    if not old.exists():
        print(json.dumps({"ok": False, "err": "alias_not_found"}), file=sys.stderr)
        return 1
    conv = json.loads(old.read_text(encoding="utf-8"))
    conv["alias"] = args.to
    new = conv_path(args.to)
    new.write_text(json.dumps(conv, indent=2), encoding="utf-8")
    old.unlink()
    print(json.dumps({"ok": True, "alias": args.to, "session": conv["session"]}))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    ensure_home()
    old = conv_path(args.alias)
    if not old.exists():
        print(json.dumps({"ok": False, "err": "alias_not_found"}), file=sys.stderr)
        return 1
    conv = json.loads(old.read_text(encoding="utf-8"))
    conv["status"] = "stopped"
    conv["stopped_at"] = now_iso()
    old.write_text(json.dumps(conv, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "alias": args.alias, "status": "stopped"}))
    return 0


def cmd_invoke(args: argparse.Namespace) -> int:
    ensure_home()
    cpath = conv_path(args.alias)
    if not cpath.exists():
        print(json.dumps({"ok": False, "err": "alias_not_active"}), file=sys.stderr)
        return 1
    conv = json.loads(cpath.read_text(encoding="utf-8"))
    rules = (
        f"# Règles de session — {args.alias}\n"
        f"Shard : {conv['shard_id']}\n"
        f"Session : {conv['session']}\n"
        "Règle d'or : aucun seal sans observe + gate PASS dans la même session.\n"
        "Intents autorisés : hygiene, closure, wip.\n"
    )
    print(rules)
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    ensure_home()
    cpath = conv_path(args.alias)
    if not cpath.exists():
        print(json.dumps({"ok": False, "err": "alias_not_active"}), file=sys.stderr)
        return 1
    conv = json.loads(cpath.read_text(encoding="utf-8"))

    lock = lock_path(args.session)
    try:
        lock.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        print(json.dumps({"ok": False, "err": "session_locked"}), file=sys.stderr)
        return 1

    scope_repos = args.scope_repos.split(",") if args.scope_repos else []
    baseline: Dict[str, List[str]] = {}
    for repo in scope_repos:
        snap = _snapshot_repo(repo)
        if snap is None:
            if lock.exists():
                lock.rmdir()
            print(
                json.dumps({"ok": False, "err": "snapshot_failed", "repo": repo}),
                file=sys.stderr,
            )
            return 1
        baseline[repo] = sorted(snap)

    state = {
        "session": args.session,
        "alias": args.alias,
        "shard_id": conv["shard_id"],
        "objective": args.objective,
        "scope_repos": scope_repos,
        "baseline": baseline,
        "started": now_iso(),
        "observes": [{"at": now_iso(), "repos": scope_repos}],
    }
    session_path(args.session).write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "session": args.session,
                "baseline_counts": {r: len(v) for r, v in baseline.items()},
            },
            indent=2,
        )
    )
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    ensure_home()
    sf = session_path(args.session)
    if not sf.exists():
        print(json.dumps({"ok": False, "err": "session_not_found"}), file=sys.stderr)
        return 1
    s = json.loads(sf.read_text(encoding="utf-8"))
    try:
        artifacts = json.loads(Path(args.artifacts).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            json.dumps({"ok": False, "err": "artifacts_invalid", "detail": str(e)}),
            file=sys.stderr,
        )
        return 1
    required = {"path", "owner", "dest", "cmd"}
    invalid = [i for i, art in enumerate(artifacts) if not required <= art.keys()]
    if invalid:
        print(
            json.dumps({"ok": False, "err": "incomplete", "indices": invalid}),
            file=sys.stderr,
        )
        return 1
    bad_dest = [a_["path"] for a_ in artifacts if a_["dest"] not in ("track", "ignore", "rm", "move")]
    if bad_dest:
        print(
            json.dumps({"ok": False, "err": "invalid_dest", "paths": bad_dest}),
            file=sys.stderr,
        )
        return 1
    s["triage"] = {"at": now_iso(), "artifacts": artifacts}
    sf.write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "triaged": len(artifacts)}))
    return 0


def _check_repo(repo: str, alias: str, check_wal: bool = False) -> tuple[list[tuple[str, str]], dict]:
    """Vérifie tree propre + commits pushés + WAL SESSION dans git log."""
    issues: list[tuple[str, str]] = []
    wal_refs: dict = {}

    # Trouver la racine du git et limiter le status au sous-dossier du repo
    # (évite les faux positifs tree_dirty depuis des fichiers hors scope)
    rc_root, root_out, _ = _run(["git", "-C", repo, "rev-parse", "--show-toplevel"])
    if rc_root == 0 and root_out.strip():
        git_root = root_out.strip()
        rel_path = os.path.relpath(repo, git_root)
        rc, out, _ = _run(["git", "-C", git_root, "status", "--porcelain", "--", rel_path])
    else:
        rc, out, _ = _run(["git", "-C", repo, "status", "--porcelain"])

    if rc != 0:
        issues.append(("tree_dirty", f"git_failed:{repo}"))
    elif out.strip():
        issues.append(("tree_dirty", f"{repo}:{len(out.splitlines())}_files"))

    rc, out, _ = _run(["git", "-C", repo, "rev-list", "--count", "@{u}..HEAD"])
    if rc == 0 and out.strip() and out.strip() != "0":
        issues.append(("not_pushed", f"{repo}:{out.strip()}_ahead"))

    if check_wal:
        rc, out, _ = _run(["git", "-C", repo, "log", "--all", "--grep",
                            f"WAL-SESSION-.*-{alias}-", "--oneline", "-1"])
        if rc == 0 and out.strip():
            wal_refs[repo] = out.split()[0]
        else:
            issues.append(("wal_missing", repo))

    return issues, wal_refs


def cmd_gate(args: argparse.Namespace) -> int:
    ensure_home()
    sf = session_path(args.session)
    if not sf.exists():
        print(json.dumps({"ok": False, "err": "session_not_found"}), file=sys.stderr)
        return 1
    s = json.loads(sf.read_text(encoding="utf-8"))
    issues: List[tuple[str, str]] = []

    if args.intent == "wip":
        for repo in s.get("scope_repos", []):
            ri, det = _wip_check(repo, s.get("baseline", {}).get(repo))
            issues.extend(ri)
            for k, v in det.items():
                issues.append(
                    (k, ";".join(v) if isinstance(v, list) else str(v))
                )
        if not issues:
            s["wip_failures"] = []
            s["wip_resolved"] = True
        else:
            s.setdefault("wip_failures", []).append(
                {"at": now_iso(), "reasons": sorted({r for r, _ in issues})}
            )
        s["last_wip"] = {"at": now_iso(), "result": "PASS" if not issues else "FAIL"}
    else:  # closure / hygiene
        wal_refs: dict = {}
        if not s.get("triage"):
            issues.append(("triage_missing", "no triage recorded for session"))
        if (
            args.intent == "closure"
            and s.get("wip_failures")
            and not s.get("wip_resolved")
        ):
            issues.append(
                ("wip_unresolved", f"{len(s['wip_failures'])} failed wip(s)")
            )
        for repo in s.get("scope_repos", []):
            ri, det = _wip_check(repo, s.get("baseline", {}).get(repo))
            issues.extend(ri)
            for k, v in det.items():
                issues.append(
                    (k, ";".join(v) if isinstance(v, list) else str(v))
                )
        for repo in s.get("scope_repos", []):
            ri, wal = _check_repo(repo, s["alias"])
            issues.extend(ri)
            wal_refs.update(wal)
        if not issues and args.intent == "hygiene":
            s["wip_failures"] = []
            s["wip_resolved"] = True

    result = {
        "ok": not issues,
        "session": args.session,
        "gate": "PASS" if not issues else "FAIL",
        "intent": args.intent,
        "issues": [{"reason": r, "detail": d} for r, d in issues],
    }
    if args.intent != "wip":
        s["last_gate"] = {"result": result, "ts": now_iso()}
    sf.write_text(json.dumps(s, indent=2), encoding="utf-8")
    if issues:
        esc = {
            "event": "escalate",
            "actor": "harness",
            "from": "gate",
            "session": args.session,
            "alias": s["alias"],
            "intent": args.intent,
            "reasons": sorted({r for r, _ in issues}),
            "hitl": True,
        }
        print(json.dumps(esc, indent=2), file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 0 if not issues else 1


def cmd_seal(args: argparse.Namespace) -> int:
    ensure_home()
    sf = session_path(args.session)
    if not sf.exists():
        print(json.dumps({"ok": False, "err": "session_not_found"}), file=sys.stderr)
        return 1
    s = json.loads(sf.read_text(encoding="utf-8"))
    lg = s.get("last_gate")
    if not lg or lg.get("result", {}).get("intent") not in ("closure", "hygiene"):
        esc = {
            "event": "escalate",
            "actor": "harness",
            "from": "seal",
            "session": args.session,
            "alias": s["alias"],
            "reason": "no last_gate in closure/hygiene",
            "hitl": True,
        }
        print(json.dumps(esc, indent=2), file=sys.stderr)
        print(
            json.dumps(
                {"ok": False, "err": "seal_requires_gate", "session": args.session}
            )
        )
        return 1
    if not lg.get("result", {}).get("ok"):
        esc = {
            "event": "escalate",
            "actor": "harness",
            "from": "seal",
            "session": args.session,
            "alias": s["alias"],
            "reason": "last_gate not PASS",
            "hitl": True,
        }
        print(json.dumps(esc, indent=2), file=sys.stderr)
        print(
            json.dumps(
                {"ok": False, "err": "last_gate_not_pass", "session": args.session}
            )
        )
        return 1

    wal_id = f"WAL-SEAL-{s['shard_id']}-{args.session}"
    s["seal"] = {"at": now_iso(), "wal": wal_id, "gate": lg}
    sf.write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "session": args.session,
                "wal": wal_id,
                "gate": lg["result"]["intent"],
            }
        )
    )
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    ensure_home()
    sf = session_path(args.session)
    lock = lock_path(args.session)
    try:
        if sf.exists():
            sf.unlink()
        if lock.exists():
            lock.rmdir()
    except OSError as e:
        print(
            json.dumps({"ok": False, "err": "abandon_failed", "detail": str(e)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"ok": True, "abandoned": args.session}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness de discipline ENV6")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.set_defaults(fn=cmd_init)

    p_new = sub.add_parser("new-conv")
    p_new.add_argument("--alias", required=True)
    p_new.set_defaults(fn=cmd_new_conv)

    p_list = sub.add_parser("list")
    p_list.set_defaults(fn=cmd_list)

    p_rename = sub.add_parser("rename")
    p_rename.add_argument("--alias", required=True)
    p_rename.add_argument("--to", required=True)
    p_rename.set_defaults(fn=cmd_rename)

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--alias", required=True)
    p_stop.set_defaults(fn=cmd_stop)

    p_invoke = sub.add_parser("invoke")
    p_invoke.add_argument("--alias", required=True)
    p_invoke.set_defaults(fn=cmd_invoke)

    p_observe = sub.add_parser("observe")
    p_observe.add_argument("--session", required=True)
    p_observe.add_argument("--alias", required=True)
    p_observe.add_argument("--objective", required=True)
    p_observe.add_argument("--scope-repos", required=True)
    p_observe.set_defaults(fn=cmd_observe)

    p_triage = sub.add_parser("triage")
    p_triage.add_argument("--session", required=True)
    p_triage.add_argument("--artifacts", required=True)
    p_triage.set_defaults(fn=cmd_triage)

    p_gate = sub.add_parser("gate")
    p_gate.add_argument("--session", required=True)
    p_gate.add_argument(
        "--intent", choices=["closure", "hygiene", "wip"], default="closure"
    )
    p_gate.set_defaults(fn=cmd_gate)

    p_seal = sub.add_parser("seal")
    p_seal.add_argument("--session", required=True)
    p_seal.set_defaults(fn=cmd_seal)

    p_abandon = sub.add_parser("abandon")
    p_abandon.add_argument("--session", required=True)
    p_abandon.set_defaults(fn=cmd_abandon)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
