import json
import sqlite3
from collections.abc import Iterable

from device.page_identity import SamplePosition
from device.source_read import LocatedSample
from station.samples import RawValue


class SpillStore:
    def __init__(self, db: sqlite3.Connection, capacity: int) -> None:
        if type(capacity) is not int or not 0 <= capacity < 2**63:
            raise ValueError('spill capacity must be a nonnegative SQLite integer')
        self.db = db
        self.configured_capacity = capacity

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS spill_config (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                capacity INTEGER NOT NULL CHECK (capacity >= 0)
            )
        ''')
        self.db.execute('INSERT OR IGNORE INTO spill_config VALUES (1, ?)',
                        (self.configured_capacity,))
        if self.capacity() != self.configured_capacity:
            raise ValueError('existing station has a different fixed spill capacity')
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS protected_samples (
                page_id INTEGER NOT NULL,
                original_index INTEGER NOT NULL,
                sample TEXT NOT NULL,
                PRIMARY KEY (page_id, original_index)
            )
        ''')

    def capacity(self) -> int:
        return self.db.execute('SELECT capacity FROM spill_config').fetchone()[0]

    def used(self) -> int:
        return self.db.execute('SELECT count(*) FROM protected_samples').fetchone()[0]

    def stage(self, samples: tuple[LocatedSample, ...]) -> None:
        if self.used() + len(samples) > self.capacity():
            raise RuntimeError('protected samples would exceed fixed capacity')
        self.db.executemany('INSERT INTO protected_samples VALUES (?, ?, ?)', (
            (sample.position.page.page_id, sample.position.index, json.dumps(sample.value.pack()))
            for sample in samples
        ))

    def fetch(self, position: SamplePosition) -> RawValue | None:
        row = self.db.execute('''
            SELECT sample FROM protected_samples WHERE page_id = ? AND original_index = ?
        ''', (position.page.page_id, position.index)).fetchone()
        return None if row is None else RawValue.unpack(json.loads(row['sample']))

    def release(self, positions: Iterable[SamplePosition]) -> None:
        self.db.executemany('''
            DELETE FROM protected_samples WHERE page_id = ? AND original_index = ?
        ''', ((position.page.page_id, position.index) for position in positions))
