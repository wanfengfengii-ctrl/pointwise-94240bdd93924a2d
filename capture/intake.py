import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from capture.local_store import StationStore
from capture.spill import SpillStore
from capture.write_admission import plan_overwrite
from delivery.cursors import CursorLedger
from device.banks import SlotBank
from device.capture import DeviceWriter
from device.page_identity import PageIdentity, SlotVersion
from device.slot_order import SlotOrder, WriteTarget
from device.source_read import DeviceSourceReader
from station.page_schema import ValidatedPage, validate_page
from station.samples import RawToken
from station.shift import ShiftProfiles


@dataclass(frozen=True)
class IntakeResult:
    status: Literal['captured', 'pending', 'device_failed']
    target: WriteTarget
    required: int
    capacity: int
    version: SlotVersion | None = None


@dataclass(frozen=True)
class PendingRequest:
    target: WriteTarget
    shift_id: str
    fingerprint: str


class _RejectedWrite(Exception):
    def __init__(self, outcome: IntakeResult) -> None:
        super().__init__('device rejected page')
        self.outcome = outcome


def _request_fingerprint(page: ValidatedPage) -> str:
    data = [page.shift_id, page.unit.value, [value.token for value in page.values]]
    encoded = json.dumps(data, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


class CaptureIntake:
    def __init__(self, store: StationStore, shifts: ShiftProfiles, order: SlotOrder,
                 bank: SlotBank, source: DeviceSourceReader, spill: SpillStore,
                 cursors: CursorLedger, writer: DeviceWriter) -> None:
        self.store = store
        self.shifts = shifts
        self.order = order
        self.bank = bank
        self.source = source
        self.spill = spill
        self.cursors = cursors
        self.writer = writer

    def initialize(self) -> None:
        self.store.db.execute('''
            CREATE TABLE IF NOT EXISTS pending_capture (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                slot INTEGER NOT NULL,
                page_id INTEGER NOT NULL,
                shift_id TEXT NOT NULL REFERENCES shifts (shift_id),
                fingerprint TEXT NOT NULL
            )
        ''')

    def pending_request(self) -> PendingRequest | None:
        row = self.store.db.execute('SELECT * FROM pending_capture').fetchone()
        if row is None:
            return None
        target = WriteTarget(row['slot'], PageIdentity(row['page_id']))
        return PendingRequest(target, row['shift_id'], row['fingerprint'])

    def submit(self, shift_id: str, unit: str,
               samples: Iterable[tuple[int, RawToken]]) -> IntakeResult:
        try:
            with self.store.transaction():
                profile = self.shifts.require_frozen(shift_id)
                page = validate_page(profile, unit, samples)
                target = self.order.next_target()
                request = PendingRequest(target, shift_id, _request_fingerprint(page))
                pending = self.pending_request()
                if pending is not None and pending != request:
                    raise ValueError('the next request must match the pending original page')
                previous = self.bank.get_slot(target.slot)
                previous_page = None if previous is None else previous.version.page
                plan = plan_overwrite(previous_page, self.cursors, self.spill)
                if not plan.allowed:
                    self.store.db.execute('''
                        INSERT INTO pending_capture VALUES (1, ?, ?, ?, ?)
                        ON CONFLICT (singleton) DO NOTHING
                    ''', (target.slot, target.page.page_id, shift_id, request.fingerprint))
                    return IntakeResult('pending', target, plan.required, plan.capacity)
                if previous is not None and plan.positions:
                    protected = self.source.read_positions(previous.version, plan.positions)
                    self.spill.stage(protected)
                written = self.writer.write_page(target, page)
                if written.version is None:
                    raise _RejectedWrite(IntakeResult('device_failed', target, plan.required,
                                                      plan.capacity))
                self.store.db.execute('DELETE FROM pending_capture WHERE singleton = 1')
                return IntakeResult('captured', target, plan.required, plan.capacity, written.version)
        except _RejectedWrite as error:
            return error.outcome


def capture_page(intake: CaptureIntake, shift_id: str, unit: str,
                 samples: Iterable[tuple[int, RawToken]]) -> IntakeResult:
    return intake.submit(shift_id, unit, samples)
