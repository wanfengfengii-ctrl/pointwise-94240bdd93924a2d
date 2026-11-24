from capture.local_store import StationStore
from delivery.closeout import require_completed_ticket
from delivery.history import BlockJournal
from delivery.tickets import TicketBook
from review.counts import sum_counts
from review.peak import merge_peaks
from review.receipts import ReceiptStore, ReviewReceipt
from review.receipts import ReviewStatement as ReviewStatement


def finish_review(store: StationStore, tickets: TicketBook, journal: BlockJournal,
                  receipts: ReceiptStore, ticket_id: int) -> ReviewReceipt:
    with store.transaction():
        ticket = tickets.get(ticket_id)
        existing = receipts.find_by_ticket(ticket.ticket_id)
        if existing is not None:
            return existing
        complete = require_completed_ticket(ticket, journal)
        statement = ReviewStatement(
            ticket.ticket_id, ticket.shift_id, ticket.unit, ticket.page, ticket.start, ticket.stop,
            sum_counts(block.counts for block in complete.evidence),
            merge_peaks(block.peak for block in complete.evidence),
        )
        return receipts.issue(statement)
