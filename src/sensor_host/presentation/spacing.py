"""Semantic spacing tokens shared by the PyQt presentation layer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Spacing:
    """Provide the approved balanced layout distances in pixels."""

    tight: int = 4
    compact: int = 8
    normal: int = 12
    section: int = 16
    major: int = 24


SPACE = Spacing()
