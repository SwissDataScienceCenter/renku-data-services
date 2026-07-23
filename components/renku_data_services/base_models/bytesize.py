"""Byte size model with unit conversions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class ByteSize:
    """Represents a size in bytes, with convenience conversions and formatting."""

    value: int

    # Binary (1024-based) unit thresholds
    KIBI = 1024
    MEBI = 1024**2
    GIBI = 1024**3
    TEBI = 1024**4

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"ByteSize cannot be negative: {self.value}")
        if not isinstance(self.value, int):
            raise TypeError(f"ByteSize value must be int, got {type(self.value).__name__}")

    def to_bytes(self) -> int:
        """Return the size in bytes."""
        return self.value

    def to_kibi(self) -> float:
        """Return the size in kibibytes (KiB)."""
        return self.value / self.KIBI

    def to_mibi(self) -> float:
        """Return the size in mebibytes (MiB)."""
        return self.value / self.MEBI

    def to_gibi(self) -> float:
        """Return the size in gibibytes (GiB)."""
        return self.value / self.GIBI

    def to_tebi(self) -> float:
        """Return the size in tebibytes (TiB)."""
        return self.value / self.TEBI

    def to_human(self) -> str:
        """Return a human-readable string with the appropriate binary unit."""
        if self.value < self.KIBI:
            return f"{self.value}B"
        elif self.value < self.MEBI:
            return f"{self.to_kibi():.2f}KiB"
        elif self.value < self.GIBI:
            return f"{self.to_mibi():.2f}MiB"
        elif self.value < self.TEBI:
            return f"{self.to_gibi():.2f}GiB"
        else:
            return f"{self.to_tebi():.2f}TiB"

    def __str__(self) -> str:
        return self.to_human()

    def __repr__(self) -> str:
        return f"ByteSize({self.value}B)"

    def __add__(self, other: ByteSize) -> ByteSize:
        return ByteSize(self.value + other.value)

    def __sub__(self, other: ByteSize) -> ByteSize:
        result = self.value - other.value
        if result < 0:
            raise ValueError("Subtraction would result in negative ByteSize")
        return ByteSize(result)

    def __radd__(self, other: int) -> ByteSize:
        # allows sum([ByteSize(1), ByteSize(2)]) to work, since sum() starts with 0
        if other == 0:
            return self
        return NotImplemented

    @classmethod
    def from_bytes(cls, bs: int) -> ByteSize:
        """Create a ByteSize from a byte count."""
        return ByteSize(value=bs)

    @classmethod
    def from_kibi(cls, kb: float) -> ByteSize:
        """Create a ByteSize from a kibibyte value."""
        return ByteSize(value=int(kb * cls.KIBI))

    @classmethod
    def from_mibi(cls, mb: float) -> ByteSize:
        """Create a ByteSize from a mebibyte value."""
        return ByteSize(value=int(mb * cls.MEBI))

    @classmethod
    def from_gibi(cls, gb: float) -> ByteSize:
        """Create a ByteSize from a gibibyte value."""
        return ByteSize(value=int(gb * cls.GIBI))

    @classmethod
    def from_tebi(cls, tib: float) -> ByteSize:
        """Create a ByteSize from a tebibyte value."""
        return cls(value=round(tib * cls.TEBI))
