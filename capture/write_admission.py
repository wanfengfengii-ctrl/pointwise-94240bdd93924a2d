from dataclasses import dataclass

from capture.spill import SpillStore
from delivery.cursors import CursorLedger
from device.page_identity import PageIdentity


@dataclass(frozen=True)
class OverwritePlan:
    positions: tuple[int, ...]
    occupied: int
    capacity: int

    @property
    def required(self) -> int:
        return self.occupied + len(self.positions)

    @property
    def allowed(self) -> bool:
        return self.required <= self.capacity


def plan_overwrite(page: PageIdentity | None, cursors: CursorLedger,
                   spill: SpillStore) -> OverwritePlan:
    spans = () if page is None else cursors.remaining_for_page(page)
    positions = {index for span in spans for index in range(span.start, span.stop)}
    return OverwritePlan(tuple(sorted(positions)), spill.used(), spill.capacity())
