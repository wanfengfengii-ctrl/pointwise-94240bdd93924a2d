import sqlite3
from dataclasses import dataclass

from delivery.tickets import Ticket
from device.page_identity import PageIdentity


@dataclass(frozen=True)
class OpenObligation:
    """Unread positions a ticket still needs after the next successful overwrite.

    ``pages`` holds every original page the obligation applies to. An unbound
    choice ticket is still a candidate on both original pages; an ordinary or
    already bound ticket holds its unread positions on one page only.
    """

    ticket_id: int
    start: int
    stop: int
    pages: tuple[PageIdentity, ...]
    choice_candidate: bool


class CursorLedger:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def open_obligations(self) -> tuple[OpenObligation, ...]:
        rows = self.db.execute('''
            SELECT ticket_id, page_id, alt_page_id, bound_page_id, kind, next_pos, stop_pos
            FROM tickets WHERE next_pos < stop_pos ORDER BY ticket_id
        ''')
        obligations = []
        for row in rows:
            if row['kind'] == 'choice' and row['bound_page_id'] is None:
                pages = (PageIdentity(row['page_id']), PageIdentity(row['alt_page_id']))
                obligations.append(OpenObligation(row['ticket_id'], row['next_pos'],
                                                  row['stop_pos'], pages, True))
            elif row['kind'] == 'choice':
                obligations.append(OpenObligation(row['ticket_id'], row['next_pos'],
                                                  row['stop_pos'],
                                                  (PageIdentity(row['bound_page_id']),), False))
            else:
                obligations.append(OpenObligation(row['ticket_id'], row['next_pos'],
                                                  row['stop_pos'],
                                                  (PageIdentity(row['page_id']),), False))
        return tuple(obligations)

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
