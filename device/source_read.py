from collections.abc import Callable, Iterable
from dataclasses import dataclass

from device.banks import SlotBank, SlotPage
from device.page_identity import PageIdentity, SamplePosition, SlotVersion
from station.samples import RawValue

ReadHook = Callable[[SamplePosition], None]


class SourceReadError(OSError):
    """An original sample could not be read."""


@dataclass(frozen=True)
class LocatedSample:
    position: SamplePosition
    value: RawValue


class DeviceSourceReader:
    def __init__(self, bank: SlotBank, before_read: ReadHook | None = None) -> None:
        self.bank = bank
        self.before_read = before_read

    def current_source(self, page: PageIdentity) -> SlotPage | None:
        return self.bank.find_current_page(page)

    def check_read(self, point: SamplePosition) -> None:
        if self.before_read is not None:
            self.before_read(point)

    def read_positions(self, version: SlotVersion,
                       positions: Iterable[int]) -> tuple[LocatedSample, ...]:
        source = self.bank.get_slot(version.slot)
        if source is None or source.version != version:
            raise SourceReadError(f'original page {version.page.page_id} is outside its device slot')
        result = []
        for index in positions:
            if type(index) is not int or not 0 <= index < len(source.values):
                raise SourceReadError(f'invalid original position {index!r}')
            point = SamplePosition(version.page, index)
            self.check_read(point)
            result.append(LocatedSample(point, source.values[index]))
        return tuple(result)
