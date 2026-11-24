import sqlite3
from dataclasses import dataclass

from device.page_identity import PageIdentity

SLOT_COUNT = 2


@dataclass(frozen=True)
class WriteTarget:
    slot: int
    page: PageIdentity


class SlotOrder:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS slot_order (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                next_slot INTEGER NOT NULL,
                next_page_id INTEGER NOT NULL
            )
        ''')
        self.db.execute('INSERT OR IGNORE INTO slot_order VALUES (1, 0, 1)')

    def next_target(self) -> WriteTarget:
        row = self.db.execute('SELECT next_slot, next_page_id FROM slot_order').fetchone()
        return WriteTarget(row['next_slot'], PageIdentity(row['next_page_id']))

    def record_success(self, target: WriteTarget) -> None:
        result = self.db.execute('''
            UPDATE slot_order SET next_slot = ?, next_page_id = ?
            WHERE singleton = 1 AND next_slot = ? AND next_page_id = ?
        ''', ((target.slot + 1) % SLOT_COUNT, target.page.page_id + 1,
              target.slot, target.page.page_id))
        if result.rowcount != 1:
            raise RuntimeError('device write target changed')
