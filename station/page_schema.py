from collections.abc import Iterable
from dataclasses import dataclass

from station.samples import RawToken, RawValue, decode_raw_value
from station.shift import ShiftProfile
from station.units import MeasurementUnit, require_page_unit


@dataclass(frozen=True)
class ValidatedPage:
    shift_id: str
    unit: MeasurementUnit
    values: tuple[RawValue, ...]


def validate_page(profile: ShiftProfile, unit: str,
                  samples: Iterable[tuple[int, RawToken]]) -> ValidatedPage:
    measured_unit = require_page_unit(unit, profile.unit)
    values = []
    for expected, sample in enumerate(samples):
        if expected >= profile.page_length:
            raise ValueError('page has more samples than the frozen page length')
        try:
            position, token = sample
        except (TypeError, ValueError) as error:
            raise ValueError('each sample needs an original position and a raw value') from error
        if type(position) is not int or position != expected:
            raise ValueError(f'expected original position {expected}')
        values.append(decode_raw_value(token, profile.rule))
    if len(values) != profile.page_length:
        raise ValueError(f'expected {profile.page_length} samples, got {len(values)}')
    return ValidatedPage(profile.shift_id, measured_unit, tuple(values))
