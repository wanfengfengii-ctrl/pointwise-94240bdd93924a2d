from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from station.samples import RawValue


@dataclass(frozen=True)
class SampleCounts:
    valid: int
    missing: int

    @property
    def total(self) -> int:
        return self.valid + self.missing


def count_block(values: Sequence[RawValue]) -> SampleCounts:
    missing = sum(value.is_missing for value in values)
    return SampleCounts(len(values) - missing, missing)


def sum_counts(blocks: Iterable[SampleCounts]) -> SampleCounts:
    valid = missing = 0
    for block in blocks:
        valid += block.valid
        missing += block.missing
    return SampleCounts(valid, missing)
