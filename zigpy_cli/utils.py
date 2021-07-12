from __future__ import annotations


def format_bytes(data: bytes) -> str:
    return ":".join(f"{b:02x}" for b in data.serialize())
