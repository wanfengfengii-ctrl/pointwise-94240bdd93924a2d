from capture.local_store import StationStore
from delivery.choice import load_choice
from delivery.closeout import IncompleteTicketError
from delivery.history import BlockJournal
from delivery.tickets import TicketBook
from review.counts import sum_counts
from review.peak import merge_peaks
from review.receipts import ReceiptStore, ReviewReceipt
from review.receipts import ReviewStatement as ReviewStatement
from station.units import MeasurementUnit


def finish_choice(store: StationStore, tickets: TicketBook, journal: BlockJournal,
                  receipts: ReceiptStore, ticket_id: int) -> ReviewReceipt:
    with store.transaction():
        choice = load_choice(tickets, ticket_id)
        existing = receipts.find_by_ticket(ticket_id)
        if existing is not None:
            return existing
        if choice.bound_page is None or choice.next_position != choice.stop:
            raise IncompleteTicketError(f'choice ticket {ticket_id} still has unread samples')
        evidence = journal.for_ticket(ticket_id)
        frontier = choice.start
        for block in evidence:
            if (block.page != choice.bound_page or block.start != frontier
                    or not frontier < block.stop <= choice.stop
                    or block.counts.total != block.stop - block.start):
                raise IncompleteTicketError(
                    f'choice ticket {ticket_id} has inconsistent block evidence')
            frontier = block.stop
        if frontier != choice.stop:
            raise IncompleteTicketError(f'choice ticket {ticket_id} lacks evidence through its end')
        statement = ReviewStatement(
            ticket_id, choice.shift_id, MeasurementUnit(choice.unit), choice.bound_page,
            choice.start, choice.stop,
            sum_counts(block.counts for block in evidence),
            merge_peaks(block.peak for block in evidence),
        )
        return receipts.issue(statement)
