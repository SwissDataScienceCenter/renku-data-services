"""Non empty list."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from dataclasses import field as data_field


@dataclass
class Nel[A]:
    """A non empty list."""

    value: A
    more_values: list[A] = data_field(default_factory=list)

    @classmethod
    def of(cls, el: A, *args: A) -> Nel[A]:
        """Constructor using varargs."""
        return Nel(value=el, more_values=list(args))

    @classmethod
    def unsafe_from_list(cls, els: list[A]) -> Nel[A]:
        """Creates a non-empty list from a list, failing if the argument is empty."""
        return Nel(els[0], els[1:])

    @classmethod
    def from_list(cls, els: list[A]) -> Nel[A] | None:
        """Creates a non-empty list from a list."""
        if els == []:
            return None
        else:
            return cls.unsafe_from_list(els)

    def __iter__(self) -> Iterator[A]:
        return _NelIterator(self.value, self.more_values)

    def __getitem__(self, index: int) -> A:
        if index == 0:
            return self.value
        else:
            return self.more_values[index - 1]

    def __len__(self) -> int:
        return len(self.more_values) + 1

    def append(self, other: Iterable[A]) -> Nel[A]:
        """Append other to this list."""
        if not other:
            return self
        else:
            remain = self.more_values.copy()
            remain.extend(other)
            return Nel(self.value, remain)

    def to_list(self) -> list[A]:
        """Convert to a list."""
        lst = [self.value]
        lst.extend(self.more_values)
        return lst

    def to_set(self) -> set[A]:
        """Convert to a set."""
        return set(self.more_values) | {self.value}

    def mk_string(self, sep: str, f: Callable[[A], str] = str) -> str:
        """Create a str from all elements mapped over f."""
        return sep.join([f(x) for x in self])

    def map[B](self, f: Callable[[A], B]) -> Nel[B]:
        """Maps `f` over this list."""
        head = f(self.value)
        rest = [f(x) for x in self.more_values]
        return Nel(head, rest)


class _NelIterator[A](Iterator[A]):
    """Iterator for non empty lists."""

    def __init__(self, head: A, tail: list[A]) -> None:
        self._head = head
        self._tail = tail
        self._tail_len = len(tail)
        self._index = 0

    def __iter__(self) -> Iterator[A]:
        return self

    def __next__(self) -> A:
        if self._index == 0:
            self._index += 1
            return self._head
        else:
            idx = self._index - 1
            if idx < self._tail_len:
                item = self._tail[idx]
                self._index += 1
                return item
            else:
                raise StopIteration
