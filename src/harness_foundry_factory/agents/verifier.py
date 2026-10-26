"""Independent verifier contract: code/expected identity, CAS-only inputs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class VerifierContractError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise VerifierContractError(message)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class VerifierContract:
    verifier_id: str
    owner: str
    code_ref: str
    code_sha256: str
    expected_ref: str
    expected_sha256: str
    input_policy: str = "CAS_ONLY"
    argv: tuple[str, ...] = ()
    timeout_seconds: float = 300

    @classmethod
    def from_dict(cls, value):
        _require(isinstance(value, dict), "verifier contract must be an object")
        required = {"verifier_id", "owner", "code_ref", "code_sha256",
                    "expected_ref", "expected_sha256"}
        _require(required <= set(value) <= required | {"input_policy", "argv", "timeout_seconds"},
                 "verifier contract has missing or unsupported fields")
        for key in ("verifier_id", "owner", "code_ref", "expected_ref"):
            _require(isinstance(value[key], str) and value[key].strip(), f"{key} must be nonempty")
        for key in ("code_sha256", "expected_sha256"):
            _require(isinstance(value[key], str) and HASH_RE.fullmatch(value[key]),
                     f"{key} must be a SHA-256 hex digest")
        policy = value.get("input_policy", "CAS_ONLY")
        _require(policy == "CAS_ONLY", "only CAS_ONLY verifier inputs are supported")
        if "argv" in value:
            _require(isinstance(value["argv"], list) and bool(value["argv"])
                     and all(isinstance(x, str) and x and "\x00" not in x for x in value["argv"]),
                     "verifier argv must be a nonempty string list")
        if "timeout_seconds" in value:
            _require(isinstance(value["timeout_seconds"], (int, float))
                     and not isinstance(value["timeout_seconds"], bool)
                     and 0 < value["timeout_seconds"] <= 3600, "verifier timeout_seconds invalid")
        return cls(value["verifier_id"], value["owner"], value["code_ref"], value["code_sha256"],
                   value["expected_ref"], value["expected_sha256"], policy,
                   tuple(value.get("argv", ())), value.get("timeout_seconds", 300))

    def verify_files(self, code_path, expected_path):
        code_path, expected_path = Path(code_path).resolve(), Path(expected_path).resolve()
        _require(code_path.is_file(), "verifier code is missing")
        _require(expected_path.is_file(), "verifier expected is missing")
        code_sha, expected_sha = _hash(code_path), _hash(expected_path)
        _require(code_sha == self.code_sha256, "verifier code hash differs")
        _require(expected_sha == self.expected_sha256, "verifier expected hash differs")
        return {"status": "PASS", "verifier_id": self.verifier_id,
                "code_sha256": code_sha, "expected_sha256": expected_sha,
                "input_policy": self.input_policy, "independent": True,
                "acceptance": False}
