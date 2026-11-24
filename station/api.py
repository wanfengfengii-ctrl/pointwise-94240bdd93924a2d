from collections.abc import Iterable
from pathlib import Path

from capture.intake import CaptureIntake, IntakeResult, capture_page
from capture.local_store import StationStore
from capture.source_index import SourceIndex
from capture.spill import SpillStore
from delivery.cursors import CursorLedger
from delivery.history import BlockJournal
from delivery.read_blocks import ReadBlock, read_next
from delivery.tickets import Ticket, TicketBook, open_ticket
from device.banks import SlotBank
from device.capture import DeviceWriter, WriteRejection
from device.page_identity import PageIdentity
from device.slot_order import SlotOrder
from device.source_read import DeviceSourceReader, ReadHook
from review.receipts import ReceiptStore, ReviewReceipt, get_receipt
from review.reconcile import finish_review
from station.probes import ProbeProfile, ProbeRegistry
from station.samples import RawToken, SampleRule
from station.shift import ShiftProfile, ShiftProfiles, start_shift


class Station:
    """Compose a local station and own its SQLite connection."""

    def __init__(self, path: str | Path, *, spill_capacity: int = 4,
                 reject_write: WriteRejection | None = None,
                 before_read: ReadHook | None = None) -> None:
        self.store = StationStore(path)
        try:
            db = self.store.db
            self.probes = ProbeRegistry(db)
            self.shifts = ShiftProfiles(db)
            self.bank = SlotBank(db)
            self.order = SlotOrder(db)
            self.spill = SpillStore(db, spill_capacity)
            self.tickets = TicketBook(db)
            self.cursors = CursorLedger(db)
            self.journal = BlockJournal(db)
            self.receipts = ReceiptStore(db)
            self.device_source = DeviceSourceReader(self.bank, before_read)
            self.source = SourceIndex(self.device_source, self.spill)
            writer = DeviceWriter(self.bank, self.order, reject_write)
            self.intake = CaptureIntake(self.store, self.shifts, self.order, self.bank,
                                        self.device_source, self.spill, self.cursors, writer)
            self.initialize()
        except BaseException:
            self.store.close()
            raise

    def initialize(self) -> None:
        self.store.initialize(self.probes.initialize, self.shifts.initialize,
                              self.bank.initialize, self.order.initialize, self.spill.initialize,
                              self.tickets.initialize, self.journal.initialize,
                              self.receipts.initialize, self.intake.initialize)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> 'Station':
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def register_probe(self, profile: ProbeProfile) -> None:
        with self.store.transaction():
            self.probes.save(profile)

    def start_shift(self, shift_id: str, probe_id: str, page_length: int,
                    unit: str, rule: SampleRule) -> ShiftProfile:
        return start_shift(self.store, self.probes, self.shifts, shift_id, probe_id,
                           page_length, unit, rule)

    def capture_page(self, shift_id: str, unit: str,
                     samples: Iterable[tuple[int, RawToken]]) -> IntakeResult:
        return capture_page(self.intake, shift_id, unit, samples)

    def open_ticket(self, page: PageIdentity, start: int, stop: int) -> Ticket:
        return open_ticket(self.store, self.tickets, self.device_source, page, start, stop)

    def read_next(self, ticket_id: int, max_samples: int) -> ReadBlock:
        return read_next(self.store, self.tickets, self.cursors, self.journal,
                         self.source, self.spill, ticket_id, max_samples)

    def finish_review(self, ticket_id: int) -> ReviewReceipt:
        return finish_review(self.store, self.tickets, self.journal, self.receipts, ticket_id)

    def get_receipt(self, receipt_id: int) -> ReviewReceipt:
        return get_receipt(self.receipts, receipt_id)
