import sqlite3
from dataclasses import dataclass

from delivery.tickets import Ticket
from device.page_identity import PageIdentity


@dataclass(frozen=True)
class RemainingSpan:
    ticket_id: int
    start: int
    stop: int


class CursorLedger:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def remaining_for_page(self, page: PageIdentity) -> tuple[RemainingSpan, ...]:
        rows = self.db.execute('''
            SELECT ticket_id, next_pos, stop_pos FROM tickets
            WHERE page_id = ? AND next_pos < stop_pos ORDER BY ticket_id
        ''', (page.page_id,))
        return tuple(RemainingSpan(row['ticket_id'], row['next_pos'], row['stop_pos']) for row in rows)

    def advance(self, ticket: Ticket, stop: int) -> None:
        if not ticket.next_position < stop <= ticket.stop:
            raise ValueError('consumption must end inside the unread interval')
        updated = self.db.execute('''
            UPDATE tickets SET next_pos = ? WHERE ticket_id = ? AND next_pos = ?
        ''', (stop, ticket.ticket_id, ticket.next_position))
        if updated.rowcount != 1:
            raise RuntimeError('ticket cursor changed')


def select_block(ticket: Ticket, max_samples: int) -> range:
    if type(max_samples) is not int or max_samples < 1:
        raise ValueError('maximum sample count must be a positive integer')
    return range(ticket.next_position, min(ticket.next_position + max_samples, ticket.stop))
