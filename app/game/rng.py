"""Seeded randomness, the same Mulberry32 riftlike uses. The generator state lives on the object
it is given (any `.rs` int), so a career saved mid-way keeps drawing the same numbers when it is
loaded again."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

T = TypeVar("T")
_MASK = 0xFFFFFFFF


class HasState(Protocol):
    rs: int


def fnv1a(text: str) -> int:
    h = 2166136261
    for ch in text.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & _MASK
    return h


def _imul(a: int, b: int) -> int:
    return (a * b) & _MASK


class Rng:
    """Mulberry32."""

    def __init__(self, holder: HasState):
        self.holder = holder

    def next(self) -> float:
        self.holder.rs = (self.holder.rs + 0x6D2B79F5) & _MASK
        t = self.holder.rs
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    def int(self, n: int) -> int:
        return int(self.next() * n)

    def chance(self, p: float) -> bool:
        return self.next() < p

    def pick(self, items: Sequence[T]) -> T | None:
        if not items:
            return None
        return items[self.int(len(items))]

    def shuffle(self, items: Sequence[T]) -> list[T]:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.int(i + 1)
            out[i], out[j] = out[j], out[i]
        return out


class Seed:
    """A throwaway holder for one-off deterministic draws."""

    def __init__(self, rs: int):
        self.rs = rs
