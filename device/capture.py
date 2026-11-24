from collections.abc import Callable
from dataclasses import dataclass

from device.banks import SlotBank
from device.page_identity import SlotVersion
from device.slot_order import SlotOrder, WriteTarget
from station.page_schema import ValidatedPage

WriteRejection = Callable[[WriteTarget, ValidatedPage], bool]


@dataclass(frozen=True)
class DeviceWriteResult:
    target: WriteTarget
    version: SlotVersion | None


class DeviceWriter:
    def __init__(self, bank: SlotBank, order: SlotOrder,
                 reject_write: WriteRejection | None = None) -> None:
        self.bank = bank
        self.order = order
        self.reject_write = reject_write

    def write_page(self, target: WriteTarget, page: ValidatedPage) -> DeviceWriteResult:
        if target != self.order.next_target():
            raise RuntimeError('device write target changed')
        if self.reject_write is not None and self.reject_write(target, page):
            return DeviceWriteResult(target, None)
        previous = self.bank.get_slot(target.slot)
        generation = 1 if previous is None else previous.version.generation + 1
        version = SlotVersion(target.slot, generation, target.page)
        self.bank.replace_page(version, page)
        self.order.record_success(target)
        return DeviceWriteResult(target, version)
