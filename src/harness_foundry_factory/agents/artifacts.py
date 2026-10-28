"""Staging -> CAS artifact ingestion (contract independence baseline)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

CAS_SCHEMA = "FOUNDRY_CAS_MANIFEST_V1"


class ArtifactStoreError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ArtifactStoreError(message)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def ingest(staging_root, cas_root, declarations, *, attempt_id):
    """Copy declared artifacts from staging to immutable CAS.

    Returns a manifest; it never overwrites an existing CAS object. Paths are
    resolved and must remain under staging. Symlinks are rejected.
    """
    staging = Path(staging_root).resolve()
    cas = Path(cas_root).resolve()
    _require(staging.is_dir(), "staging root must exist")
    _require(cas.is_dir(), "CAS root must exist")
    _require(not _inside(cas, staging) and not _inside(staging, cas),
             "CAS and staging must not contain each other")
    entries = []
    seen = set()
    for declaration in declarations:
        _require(isinstance(declaration, dict), "artifact declaration must be an object")
        artifact_id = declaration.get("artifact_id")
        relative = declaration.get("path")
        _require(isinstance(artifact_id, str) and artifact_id and artifact_id not in seen,
                 "artifact_id must be unique nonempty text")
        _require(isinstance(relative, str) and relative and ".." not in Path(relative).parts,
                 "artifact path must be a safe relative path")
        source = (staging / relative).resolve()
        _require(_inside(source, staging), "artifact escapes staging")
        _require(source.is_file() and not source.is_symlink(), "artifact must be a regular file")
        digest = _hash(source)
        target = cas / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _require(target.is_file() and _hash(target) == digest, "existing CAS object differs")
        else:
            fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
            os.close(fd)
            try:
                shutil.copy2(source, temporary)
                _require(_hash(Path(temporary)) == digest, "CAS copy hash mismatch")
                os.chmod(temporary, 0o444)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        entries.append({"artifact_id": artifact_id, "path": relative, "sha256": digest,
                        "size": source.stat().st_size, "cas_ref": f"cas://{digest}",
                        "attempt_id": attempt_id})
        seen.add(artifact_id)
    manifest = {"schema_version": CAS_SCHEMA, "attempt_id": attempt_id, "entries": entries}
    return {"status": "PASS", "manifest": manifest, "cas_root": str(cas),
            "writes_performed": bool(entries)}


def write_manifest(manifest, root):
    """Write a new manifest beside CAS; never overwrite."""
    path = Path(root) / (manifest["attempt_id"] + ".json")
    if path.exists():
        raise ArtifactStoreError("CAS manifest already exists")
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path
