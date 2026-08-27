"""Read raw SDF1 sessions in deterministic bounded chunks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


_DEFAULT_REPLAY_CHUNK_SIZE = 65_536


def replay_chunks(
    path: Path,
    chunk_size: int = _DEFAULT_REPLAY_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield a raw recording without interpreting or rewriting its bytes."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            yield chunk
