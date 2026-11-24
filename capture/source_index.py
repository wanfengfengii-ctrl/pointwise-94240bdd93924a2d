from collections.abc import Iterable

from capture.spill import SpillStore
from device.page_identity import PageIdentity, SamplePosition
from device.source_read import DeviceSourceReader, LocatedSample, SourceReadError


class SourceIndex:
    def __init__(self, device: DeviceSourceReader, spill: SpillStore) -> None:
        self.device = device
        self.spill = spill

    def read_positions(self, page: PageIdentity,
                       positions: Iterable[int]) -> tuple[LocatedSample, ...]:
        current = self.device.current_source(page)
        if current is not None:
            return self.device.read_positions(current.version, positions)
        result = []
        for index in positions:
            point = SamplePosition(page, index)
            self.device.check_read(point)
            value = self.spill.fetch(point)
            if value is None:
                raise SourceReadError(f'original page {page.page_id} position {index} unavailable')
            result.append(LocatedSample(point, value))
        return tuple(result)
