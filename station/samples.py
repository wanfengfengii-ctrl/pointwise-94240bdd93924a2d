import json
import re
from dataclasses import dataclass
from decimal import Decimal

RawToken = int | str
_DECIMAL_TOKEN = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')


def _valid_token(token: object) -> bool:
    return type(token) is int or (type(token) is str and bool(token))


def _fits_places(value: Decimal, places: int) -> bool:
    return value.as_tuple().exponent >= -places


@dataclass(frozen=True)
class SampleRule:
    minimum: Decimal
    maximum: Decimal
    places: int
    missing: RawToken

    def __post_init__(self) -> None:
        if type(self.places) is not int or self.places < 0:
            raise ValueError('decimal places must be a nonnegative integer')
        for limit in (self.minimum, self.maximum):
            if not isinstance(limit, Decimal) or not limit.is_finite():
                raise ValueError('sample limits must be finite Decimal values')
            if not _fits_places(limit, self.places):
                raise ValueError('sample limits exceed declared decimal precision')
        if self.minimum > self.maximum or not _valid_token(self.missing):
            raise ValueError('invalid sample range or missing code')

    def encode(self) -> str:
        return json.dumps([str(self.minimum), str(self.maximum), self.places, self.missing])

    @classmethod
    def decode(cls, text: str) -> 'SampleRule':
        minimum, maximum, places, missing = json.loads(text)
        return cls(Decimal(minimum), Decimal(maximum), places, missing)


@dataclass(frozen=True)
class RawValue:
    token: RawToken
    number: Decimal | None

    @property
    def is_missing(self) -> bool:
        return self.number is None

    def pack(self) -> tuple[RawToken, bool]:
        return self.token, self.is_missing

    @classmethod
    def unpack(cls, pair: tuple[RawToken, bool]) -> 'RawValue':
        token, is_missing = pair
        return cls(token, None if is_missing else Decimal(token))


def decode_raw_value(token: RawToken, rule: SampleRule) -> RawValue:
    if not _valid_token(token):
        raise ValueError('sample must be an integer or a nonempty string')
    if type(token) is type(rule.missing) and token == rule.missing:
        return RawValue(token, None)
    if type(token) is str and not _DECIMAL_TOKEN.fullmatch(token):
        raise ValueError('expected fixed decimal notation or the exact missing code')
    number = Decimal(token)
    if not _fits_places(number, rule.places):
        raise ValueError('sample exceeds declared decimal precision')
    if not rule.minimum <= number <= rule.maximum:
        raise ValueError('sample outside the frozen range')
    return RawValue(token, number)
