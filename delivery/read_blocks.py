from dataclasses import dataclass

from capture.local_store import StationStore
from capture.source_index import SourceIndex
from capture.spill import SpillStore
from capture.write_admission import release_unneeded
from delivery.cursors import CursorLedger, select_block
from delivery.history import BlockJournal
from delivery.tickets import TicketBook
from device.banks import SlotBank
from device.page_identity import SamplePosition
from device.source_read import LocatedSample, SourceReadError


@dataclass(frozen=True)
class ReadBlock:
    ticket_id: int
    start: int
    stop: int
    samples: tuple[LocatedSample, ...]


def read_next(store: StationStore, tickets: TicketBook, cursors: CursorLedger,
              journal: BlockJournal, source: SourceIndex, spill: SpillStore,
              bank: SlotBank, ticket_id: int, max_samples: int) -> ReadBlock:
    with store.transaction():
        ticket = tickets.get(ticket_id)
        positions = select_block(ticket, max_samples)
        if not positions:
            return ReadBlock(ticket_id, positions.start, positions.stop, ())
        samples = source.read_positions(ticket.page, positions)
        expected = tuple(SamplePosition(ticket.page, index) for index in positions)
        if tuple(sample.position for sample in samples) != expected:
            raise SourceReadError('read source did not return the complete original interval')
        journal.record(ticket_id, ticket.page, positions, tuple(sample.value for sample in samples))
        cursors.advance(ticket, positions.stop)
        release_unneeded(cursors, bank, spill)
        return ReadBlock(ticket_id, positions.start, positions.stop, samples)
