from enum import StrEnum


class MeasurementUnit(StrEnum):
    MICROMETRE = 'μm'
    MILLIMETRE = 'mm'


def require_page_unit(declared: str, expected: MeasurementUnit) -> MeasurementUnit:
    if not isinstance(declared, str) or declared != expected:
        raise ValueError(f'expected measurement unit {expected.value!r}')
    return expected
