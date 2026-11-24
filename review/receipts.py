import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from device.page_identity import PageIdentity, SamplePosition
from review.counts import SampleCounts
from station.units import MeasurementUnit


@dataclass(frozen=True)
class ReviewStatement:
    ticket_id: int
    shift_id: str
    unit: MeasurementUnit
    page: PageIdentity
    start: int
    stop: int
    counts: SampleCounts
    peak: Decimal | None

    @property
    def origins(self) -> tuple[SamplePosition, ...]:
        return tuple(SamplePosition(self.page, index) for index in range(self.start, self.stop))


@dataclass(frozen=True)
class ReviewReceipt:
    receipt_id: int
    statement: ReviewStatement


class ReceiptStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS review_receipts (
                receipt_id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets (ticket_id),
                statement TEXT NOT NULL
            )
        ''')

    @staticmethod
    def _decode(row: sqlite3.Row) -> ReviewReceipt:
        data = json.loads(row['statement'])
        statement = ReviewStatement(
            row['ticket_id'], data['shift_id'], MeasurementUnit(data['unit']),
            PageIdentity(data['page_id']), data['start'], data['stop'],
            SampleCounts(data['valid'], data['missing']),
            None if data['peak'] is None else Decimal(data['peak']),
        )
        return ReviewReceipt(row['receipt_id'], statement)

    def issue(self, statement: ReviewStatement) -> ReviewReceipt:
        body = {
            'shift_id': statement.shift_id,
            'unit': statement.unit.value,
            'page_id': statement.page.page_id,
            'start': statement.start,
            'stop': statement.stop,
            'valid': statement.counts.valid,
            'missing': statement.counts.missing,
            'peak': None if statement.peak is None else str(statement.peak),
        }
        inserted = self.db.execute('''
            INSERT INTO review_receipts (ticket_id, statement) VALUES (?, ?)
        ''', (statement.ticket_id, json.dumps(body, sort_keys=True)))
        return ReviewReceipt(inserted.lastrowid, statement)

    def find_by_ticket(self, ticket_id: int) -> ReviewReceipt | None:
        row = self.db.execute('SELECT * FROM review_receipts WHERE ticket_id = ?', (ticket_id,)).fetchone()
        return None if row is None else self._decode(row)

    def get(self, receipt_id: int) -> ReviewReceipt:
        if type(receipt_id) is not int or not 1 <= receipt_id < 2**63:
            raise LookupError(f'unknown receipt {receipt_id!r}')
        row = self.db.execute('SELECT * FROM review_receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown receipt {receipt_id}')
        return self._decode(row)


def get_receipt(receipts: ReceiptStore, receipt_id: int) -> ReviewReceipt:
    return receipts.get(receipt_id)
