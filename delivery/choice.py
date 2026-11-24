from dataclasses import dataclass

from capture.local_store import StationStore
from capture.source_index import SourceIndex
from capture.spill import SpillStore
from capture.write_admission import release_unneeded
from delivery.cursors import CursorLedger
from delivery.history import BlockJournal
from delivery.read_blocks import ReadBlock
from delivery.tickets import TicketBook
from device.banks import SlotBank
from device.page_identity import PageIdentity, SamplePosition
from device.source_read import SourceReadError


@dataclass(frozen=True)
class ChoiceTicket:
    ticket_id: int
    pages: tuple[PageIdentity, PageIdentity]
    shift_id: str
    unit: str
    start: int
    stop: int
    next_position: int
    bound_page: PageIdentity | None


def load_choice(tickets: TicketBook, ticket_id: int) -> ChoiceTicket:
    row = tickets.choice_row(ticket_id)
    return ChoiceTicket(
        ticket_id,
        (PageIdentity(row['page_id']), PageIdentity(row['alt_page_id'])),
        row['shift_id'], row['unit'], row['start_pos'], row['stop_pos'],
        row['next_pos'],
        None if row['bound_page_id'] is None else PageIdentity(row['bound_page_id']),
    )


def open_choice_ticket(store: StationStore, tickets: TicketBook, source: SourceIndex,
                       page_a: PageIdentity, page_b: PageIdentity,
                       start: int, stop: int) -> int:
    if not isinstance(page_a, PageIdentity) or not isinstance(page_b, PageIdentity):
        raise ValueError('choice tickets need two original page identities')
    if page_a == page_b:
        raise ValueError('choice ticket needs two different original pages')
    if type(start) is not int or type(stop) is not int:
        raise ValueError('choice ticket needs an integer half-open interval')
    if not 0 <= start < stop:
        raise ValueError('choice ticket needs a nonempty half-open interval')
    with store.transaction():
        first = source.device.current_source(page_a)
        second = source.device.current_source(page_b)
        if first is None:
            raise LookupError(f'page {page_a.page_id} is no longer current')
        if second is None:
            raise LookupError(f'page {page_b.page_id} is no longer current')
        if first.shift_id != second.shift_id:
            raise ValueError('choice ticket needs two pages of the same shift')
        if first.unit != second.unit:
            raise ValueError('choice ticket needs two pages of the same unit')
        if stop > len(first.values) or stop > len(second.values):
            raise ValueError('choice ticket interval must fit both original pages')
        return tickets.create_choice(first, second, start, stop)


def read_choice(store: StationStore, tickets: TicketBook, cursors: CursorLedger,
                journal: BlockJournal, source: SourceIndex, bank: SlotBank, spill: SpillStore,
                ticket_id: int, max_samples: int, page: PageIdentity) -> ReadBlock:
    with store.transaction():
        choice = load_choice(tickets, ticket_id)
        if type(max_samples) is not int or max_samples < 1:
            raise ValueError('maximum sample count must be a positive integer')
        if not isinstance(page, PageIdentity):
            raise ValueError('choice reads require an original page identity')
        if choice.bound_page is not None:
            if page != choice.bound_page:
                raise ValueError('choice ticket is bound to another original page')
        else:
            if page not in choice.pages:
                raise ValueError('original page is not a candidate of this ticket')
            if not source.covers(page, range(choice.start, choice.stop)):
                raise ValueError('the first block needs a complete original interval')
        positions = range(choice.next_position,
                          min(choice.next_position + max_samples, choice.stop))
        if not positions:
            return ReadBlock(ticket_id, positions.start, positions.stop, ())
        samples = source.read_positions(page, positions)
        expected = tuple(SamplePosition(page, index) for index in positions)
        if tuple(sample.position for sample in samples) != expected:
            raise SourceReadError('read source did not return the complete original interval')
        if choice.bound_page is None:
            tickets.bind_choice(ticket_id, page)
        journal.record(ticket_id, page, positions, tuple(sample.value for sample in samples))
        tickets.advance_choice(ticket_id, positions.stop)
        release_unneeded(cursors, bank, spill)
        return ReadBlock(ticket_id, positions.start, positions.stop, samples)
