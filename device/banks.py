import json
import sqlite3
from dataclasses import dataclass

from device.page_identity import PageIdentity, SlotVersion
from station.page_schema import ValidatedPage
from station.samples import RawValue
from station.units import MeasurementUnit


@dataclass(frozen=True)
class SlotPage:
    version: SlotVersion
    shift_id: str
    unit: MeasurementUnit
    values: tuple[RawValue, ...]


class SlotBank:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS device_slots (
                slot INTEGER PRIMARY KEY,
                generation INTEGER NOT NULL CHECK (generation > 0),
                page_id INTEGER NOT NULL UNIQUE,
                shift_id TEXT NOT NULL REFERENCES shifts (shift_id),
                unit TEXT NOT NULL,
                samples TEXT NOT NULL
            )
        ''')

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> SlotPage | None:
        if row is None:
            return None
        version = SlotVersion(row['slot'], row['generation'], PageIdentity(row['page_id']))
        values = tuple(RawValue.unpack(pair) for pair in json.loads(row['samples']))
        return SlotPage(version, row['shift_id'], MeasurementUnit(row['unit']), values)

    def get_slot(self, slot: int) -> SlotPage | None:
        return self._decode(self.db.execute(
            'SELECT * FROM device_slots WHERE slot = ?', (slot,)
        ).fetchone())

    def find_current_page(self, page: PageIdentity) -> SlotPage | None:
        return self._decode(self.db.execute(
            'SELECT * FROM device_slots WHERE page_id = ?', (page.page_id,)
        ).fetchone())

    def replace_page(self, version: SlotVersion, page: ValidatedPage) -> None:
        encoded = json.dumps([value.pack() for value in page.values], ensure_ascii=False)
        self.db.execute('''
            INSERT INTO device_slots VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (slot) DO UPDATE SET
                generation = excluded.generation,
                page_id = excluded.page_id,
                shift_id = excluded.shift_id,
                unit = excluded.unit,
                samples = excluded.samples
        ''', (version.slot, version.generation, version.page.page_id,
              page.shift_id, page.unit.value, encoded))
