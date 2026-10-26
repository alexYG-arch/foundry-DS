"""POSIX resource limits for trusted-host execution (best effort, not a sandbox)."""

from __future__ import annotations

import resource


def preexec(max_cpu_seconds=None, max_memory_bytes=None, max_fds=None):
    def apply():
        if max_cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (int(max_cpu_seconds), int(max_cpu_seconds)))
        if max_memory_bytes:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (int(max_memory_bytes), int(max_memory_bytes)))
            except (OSError, ValueError):
                # macOS may not support RLIMIT_AS; best effort, never a sandbox.
                pass
        if max_fds:
            resource.setrlimit(resource.RLIMIT_NOFILE, (int(max_fds), int(max_fds)))
    return apply


def truncate_output(text, max_bytes):
    if max_bytes is None or max_bytes <= 0 or text is None:
        return text
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", "ignore") + "\n[TRUNCATED]"
