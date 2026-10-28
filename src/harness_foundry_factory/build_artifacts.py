"""Named artifact facts shared by execution and repair; no scheduling authority."""
import hashlib
import os
from pathlib import Path, PurePosixPath

from .build_types import RequestValidationError

# Interpreter and tool caches may appear inside a verifier root after a check
# ran; they carry no judgment and must not read as "the checker changed".
MANIFEST_EXCLUDED_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"})
MANIFEST_EXCLUDED_FILES = frozenset({".DS_Store"})
MANIFEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def relative_path(root, value):
    _require(isinstance(value, str) and bool(value), "relative path must be text")
    relative = PurePosixPath(value)
    _require(not relative.is_absolute() and ".." not in relative.parts and "\\" not in value
           and relative.as_posix() == value, "path must be canonical and relative")
    path = (root / value).resolve()
    _require(path.is_relative_to(root), "path resolves outside the declared root")
    return path


def file_identity(path):
    # H2: only named verifier/input/output files. Never hash messages, receipts
    # or a recursive workspace tree. Missing files are a real verification gap.
    _require(path.is_file(), f"required artifact is not a file: {path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": path.stat().st_size, "sha256": digest}


def directory_manifest(root, *, max_files=2000):
    """Identity of every regular file under a host-owned verifier root.

    This is the one deliberate exception to "only named files": the verifier
    root *is* the judgment, including the helpers and fixtures a checker
    imports or reads, so a change anywhere in it must stop dispatch. The walk
    does not follow directory symlinks, skips interpreter/tool caches, and
    refuses roots large enough to suggest a checkout rather than a checker.
    """
    root = Path(root).resolve(strict=True)
    _require(root.is_dir(), f"verifier root is not a directory: {root}")
    manifest = {}
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in MANIFEST_EXCLUDED_DIRS)
        for name in sorted(filenames):
            if name in MANIFEST_EXCLUDED_FILES or name.endswith(MANIFEST_EXCLUDED_SUFFIXES):
                continue
            path = Path(current) / name
            if not path.is_file():      # sockets, fifos, dangling links carry no checker bytes
                continue
            manifest[path.relative_to(root).as_posix()] = file_identity(path)
            _require(len(manifest) <= max_files,
                     f"verifier root holds more than {max_files} files; bind a narrower checker directory")
    return manifest


def superseded_artifacts(plan, attempts):
    # Starting the explicit replacement consumes the old physical version.
    # The Plan requires all old-version readers to finish before this task.
    # Its rejected candidate can be repaired without pretending old bytes
    # still exist or allowing downstream use of the unaccepted replacement.
    started_tasks = {row["workpack_id"] for row in attempts.values() if row["status"] != "NOT_DISPATCHED"}
    return {item["replaces_artifact_id"] for task in plan["workpacks"] if task["workpack_id"] in started_tasks
            for item in task["artifacts"] if "replaces_artifact_id" in item}

def changed_accepted_files(workspace, plan, accepted, attempts):
    superseded = superseded_artifacts(plan, attempts)
    changed = {}
    for record in accepted.values():
        for identity, artifact in record["artifacts"].items():
            if identity not in superseded:
                path = relative_path(workspace, artifact["path"])
                current = file_identity(path) if path.is_file() else None
                if current != {k: artifact[k] for k in ("size", "sha256")}:
                    changed.setdefault(record["workpack_id"], []).append(identity)
    return changed

def check_accepted_files(workspace, plan, accepted, attempts):
    _require(not changed_accepted_files(workspace, plan, accepted, attempts),
           "accepted artifact changed; dependent evidence requires revalidation")

