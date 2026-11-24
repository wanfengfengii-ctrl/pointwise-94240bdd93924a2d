from dataclasses import dataclass

from delivery.history import BlockEvidence, BlockJournal
from delivery.tickets import Ticket


class IncompleteTicketError(RuntimeError):
    """The ticket lacks complete successful delivery evidence."""


@dataclass(frozen=True)
class CompletedTicket:
    ticket: Ticket
    evidence: tuple[BlockEvidence, ...]


def require_completed_ticket(ticket: Ticket, journal: BlockJournal) -> CompletedTicket:
    if ticket.next_position != ticket.stop:
        raise IncompleteTicketError(f'ticket {ticket.ticket_id} still has unread samples')
    evidence = journal.for_ticket(ticket.ticket_id)
    frontier = ticket.start
    for block in evidence:
        if (block.page != ticket.page or block.start != frontier
                or not frontier < block.stop <= ticket.stop
                or block.counts.total != block.stop - block.start):
            raise IncompleteTicketError(f'ticket {ticket.ticket_id} has inconsistent block evidence')
        frontier = block.stop
    if frontier != ticket.stop:
        raise IncompleteTicketError(f'ticket {ticket.ticket_id} lacks evidence through its end')
    return CompletedTicket(ticket, evidence)
