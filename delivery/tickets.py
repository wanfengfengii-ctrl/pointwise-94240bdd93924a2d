import sqlite3
from dataclasses import dataclass

from capture.local_store import StationStore
from device.banks import SlotPage
from device.page_identity import PageIdentity, SlotVersion
from device.source_read import DeviceSourceReader
from station.units import MeasurementUnit


@dataclass(frozen=True)
class Ticket:
    ticket_id: int
    origin: SlotVersion
    shift_id: str
    unit: MeasurementUnit
    start: int
    stop: int
    next_position: int

    @property
    def page(self) -> PageIdentity:
        return self.origin.page


class TicketBook:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def initialize(self) -> None:
        self.db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY,
                page_id INTEGER NOT NULL,
                original_slot INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                shift_id TEXT NOT NULL REFERENCES shifts (shift_id),
                unit TEXT NOT NULL,
                start_pos INTEGER NOT NULL,
                stop_pos INTEGER NOT NULL,
                next_pos INTEGER NOT NULL,
                CHECK (0 <= start_pos AND start_pos < stop_pos),
                CHECK (start_pos <= next_pos AND next_pos <= stop_pos)
            )
        ''')
        self.db.execute('CREATE INDEX IF NOT EXISTS tickets_page ON tickets (page_id)')

    def create(self, page: SlotPage, start: int, stop: int) -> Ticket:
        version = page.version
        inserted = self.db.execute('''
            INSERT INTO tickets (page_id, original_slot, generation, shift_id,
                                 unit, start_pos, stop_pos, next_pos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (version.page.page_id, version.slot, version.generation, page.shift_id,
              page.unit.value, start, stop, start))
        return Ticket(inserted.lastrowid, version, page.shift_id, page.unit, start, stop, start)

    def get(self, ticket_id: int) -> Ticket:
        if type(ticket_id) is not int or not 1 <= ticket_id < 2**63:
            raise LookupError(f'unknown ticket {ticket_id!r}')
        row = self.db.execute('SELECT * FROM tickets WHERE ticket_id = ?', (ticket_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown ticket {ticket_id}')
        origin = SlotVersion(row['original_slot'], row['generation'], PageIdentity(row['page_id']))
        return Ticket(ticket_id, origin, row['shift_id'], MeasurementUnit(row['unit']),
                      row['start_pos'], row['stop_pos'], row['next_pos'])


def open_ticket(store: StationStore, tickets: TicketBook, source: DeviceSourceReader,
                page: PageIdentity, start: int, stop: int) -> Ticket:
    with store.transaction():
        if not isinstance(page, PageIdentity):
            raise ValueError('opening a ticket requires an original page identity')
        current = source.current_source(page)
        if current is None:
            raise LookupError(f'page {page.page_id} is no longer current')
        if type(start) is not int or type(stop) is not int or not 0 <= start < stop <= len(current.values):
            raise ValueError('ticket needs a nonempty half-open interval within the page')
        return tickets.create(current, start, stop)
