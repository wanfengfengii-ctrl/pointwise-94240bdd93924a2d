import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from station.samples import SampleRule
from station.units import MeasurementUnit


@dataclass(frozen=True)
class ProbeProfile:
    probe_id: str
    unit: MeasurementUnit
    max_page_length: int
    limits: SampleRule

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id.strip():
            raise ValueError('probe id must be nonempty')
        if type(self.max_page_length) is not int or not 1 <= self.max_page_length < 2**63:
            raise ValueError('invalid probe page length')
        if not isinstance(self.unit, MeasurementUnit) or not isinstance(self.limits, SampleRule):
            raise ValueError('probe needs a measurement unit and sample limits')

    def parameters(self) -> tuple[str, str, int, str]:
        return self.probe_id, self.unit.value, self.max_page_length, self.limits.encode()


_DEFAULT_PROBE = ProbeProfile(
    'line-2', MeasurementUnit.MICROMETRE, 4,
    SampleRule(Decimal('-1000'), Decimal('1000'), 3, -9999),
)


class ProbeRegistry:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS probes (
                probe_id TEXT PRIMARY KEY,
                unit TEXT NOT NULL,
                max_page_length INTEGER NOT NULL CHECK (max_page_length > 0),
                limits TEXT NOT NULL
            )
        ''')
        self.db.execute('''
            INSERT INTO probes VALUES (?, ?, ?, ?)
            ON CONFLICT (probe_id) DO NOTHING
        ''', _DEFAULT_PROBE.parameters())

    def save(self, profile: ProbeProfile) -> None:
        self.db.execute('''
            INSERT INTO probes VALUES (?, ?, ?, ?)
            ON CONFLICT (probe_id) DO UPDATE SET
                unit = excluded.unit,
                max_page_length = excluded.max_page_length,
                limits = excluded.limits
        ''', profile.parameters())

    def require(self, probe_id: str) -> ProbeProfile:
        if not isinstance(probe_id, str):
            raise ValueError('invalid probe id')
        row = self.db.execute('SELECT * FROM probes WHERE probe_id = ?', (probe_id,)).fetchone()
        if row is None:
            raise ValueError(f'unknown probe {probe_id!r}')
        return ProbeProfile(row['probe_id'], MeasurementUnit(row['unit']),
                            row['max_page_length'], SampleRule.decode(row['limits']))
