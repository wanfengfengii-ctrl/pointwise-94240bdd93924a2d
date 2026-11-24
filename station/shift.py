import sqlite3
from dataclasses import dataclass

from capture.local_store import StationStore
from station.probes import ProbeRegistry
from station.samples import SampleRule
from station.units import MeasurementUnit, require_page_unit


@dataclass(frozen=True)
class ShiftProfile:
    shift_id: str
    probe_id: str
    page_length: int
    unit: MeasurementUnit
    rule: SampleRule


class ShiftProfiles:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS shifts (
                shift_id TEXT PRIMARY KEY,
                probe_id TEXT NOT NULL REFERENCES probes (probe_id),
                page_length INTEGER NOT NULL CHECK (page_length > 0),
                unit TEXT NOT NULL,
                rule TEXT NOT NULL
            )
        ''')

    def find(self, shift_id: str) -> ShiftProfile | None:
        if not isinstance(shift_id, str) or not shift_id.strip():
            raise ValueError('shift id must be nonempty')
        row = self.db.execute('SELECT * FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
        if row is None:
            return None
        return ShiftProfile(row['shift_id'], row['probe_id'], row['page_length'],
                            MeasurementUnit(row['unit']), SampleRule.decode(row['rule']))

    def require_frozen(self, shift_id: str) -> ShiftProfile:
        profile = self.find(shift_id)
        if profile is None:
            raise ValueError(f'no frozen profile for shift {shift_id!r}')
        return profile

    def freeze(self, profile: ShiftProfile) -> None:
        self.db.execute('INSERT INTO shifts VALUES (?, ?, ?, ?, ?)',
                        (profile.shift_id, profile.probe_id, profile.page_length,
                         profile.unit.value, profile.rule.encode()))


def start_shift(store: StationStore, probes: ProbeRegistry, shifts: ShiftProfiles,
                shift_id: str, probe_id: str, page_length: int,
                unit: str, rule: SampleRule) -> ShiftProfile:
    if type(page_length) is not int or page_length < 1 or not isinstance(rule, SampleRule):
        raise ValueError('shift needs a positive page length and a sample rule')
    with store.transaction():
        existing = shifts.find(shift_id)
        if existing is not None:
            require_page_unit(unit, existing.unit)
            if (probe_id, page_length, rule) != (existing.probe_id, existing.page_length, existing.rule):
                raise ValueError(f'conflicting frozen profile for shift {shift_id!r}')
            return existing
        probe = probes.require(probe_id)
        measured_unit = require_page_unit(unit, probe.unit)
        limits = probe.limits
        if page_length > probe.max_page_length:
            raise ValueError('shift page length exceeds probe capability')
        if (rule.minimum < limits.minimum or rule.maximum > limits.maximum
                or rule.places > limits.places or rule.missing != limits.missing):
            raise ValueError('shift sample rule exceeds probe capability')
        profile = ShiftProfile(shift_id, probe_id, page_length, measured_unit, rule)
        shifts.freeze(profile)
        return profile
