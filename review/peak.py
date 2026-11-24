from collections.abc import Iterable
from decimal import Decimal

from station.samples import RawValue


def peak_magnitude(values: Iterable[RawValue]) -> Decimal | None:
    return max((value.number.copy_abs() for value in values if value.number is not None),
               default=None)


def merge_peaks(peaks: Iterable[Decimal | None]) -> Decimal | None:
    return max((peak for peak in peaks if peak is not None), default=None)
