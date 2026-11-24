import sqlite3
from dataclasses import dataclass
from decimal import Decimal

from device.page_identity import PageIdentity
from review.counts import SampleCounts, count_block
from review.peak import peak_magnitude
from station.samples import RawValue


@dataclass(frozen=True)
class BlockEvidence:
    ticket_id: int
    page: PageIdentity
    start: int
    stop: int
    counts: SampleCounts
    peak: Decimal | None


class BlockJournal:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS delivered_blocks (
                ticket_id INTEGER NOT NULL REFERENCES tickets (ticket_id),
                page_id INTEGER NOT NULL,
                start_pos INTEGER NOT NULL,
                stop_pos INTEGER NOT NULL,
                valid_count INTEGER NOT NULL CHECK (valid_count >= 0),
                missing_count INTEGER NOT NULL CHECK (missing_count >= 0),
                peak TEXT,
                CHECK (stop_pos > start_pos),
                CHECK (valid_count + missing_count = stop_pos - start_pos),
                PRIMARY KEY (ticket_id, start_pos)
            )
        ''')

    def record(self, ticket_id: int, page: PageIdentity, positions: range,
               values: tuple[RawValue, ...]) -> BlockEvidence:
        if not values or len(values) != len(positions) or positions.step != 1:
            raise ValueError('evidence requires a complete nonempty block')
        counts = count_block(values)
        peak = peak_magnitude(values)
        self.db.execute('INSERT INTO delivered_blocks VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (ticket_id, page.page_id, positions.start, positions.stop,
                         counts.valid, counts.missing, None if peak is None else str(peak)))
        return BlockEvidence(ticket_id, page, positions.start, positions.stop, counts, peak)

    def for_ticket(self, ticket_id: int) -> tuple[BlockEvidence, ...]:
        rows = self.db.execute('''
            SELECT * FROM delivered_blocks WHERE ticket_id = ? ORDER BY start_pos
        ''', (ticket_id,))
        return tuple(
            BlockEvidence(ticket_id, PageIdentity(row['page_id']), row['start_pos'], row['stop_pos'],
                          SampleCounts(row['valid_count'], row['missing_count']),
                          None if row['peak'] is None else Decimal(row['peak']))
            for row in rows
        )
