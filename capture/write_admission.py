from dataclasses import dataclass

from capture.spill import SpillStore
from delivery.cursors import CursorLedger, OpenObligation
from device.page_identity import PageIdentity

Cell = tuple[int, int]


@dataclass(frozen=True)
class OverwritePlan:
    """Cells to retain and slots to copy out before overwriting one device slot."""

    keep: frozenset[Cell]
    stage: tuple[int, ...]
    required: int
    capacity: int
    lost: int = 0

    @property
    def allowed(self) -> bool:
        return self.lost == 0 and self.required <= self.capacity


@dataclass(frozen=True)
class _Assignment:
    keep: frozenset[Cell]
    stage: tuple[int, ...]
    lost: int = 0

    @property
    def required(self) -> int:
        return len(self.keep) + len(self.stage) + self.lost


def _span_cells(page: PageIdentity, obligation: OpenObligation) -> set[Cell]:
    return {(page.page_id, index) for index in range(obligation.start, obligation.stop)}


def _complete_before(page: PageIdentity, obligation: OpenObligation,
                     in_slot: set[int], spilled: set[Cell]) -> bool:
    """A candidate can still lead only if every position is slotted or retained."""
    return all(page.page_id in in_slot or (page.page_id, index) in spilled
               for index in range(obligation.start, obligation.stop))


def _evaluate(fixed: set[Cell], chosen: tuple[tuple[OpenObligation, PageIdentity], ...],
              previous: PageIdentity | None, resident: set[int],
              spilled: set[Cell]) -> _Assignment:
    required = set(fixed)
    for obligation, page in chosen:
        required |= _span_cells(page, obligation)
    keep: set[Cell] = set()
    stage: list[int] = []
    lost = 0
    for page_id, index in sorted(required):
        if page_id in resident:
            continue
        cell = (page_id, index)
        if cell in spilled:
            keep.add(cell)
        elif previous is not None and page_id == previous.page_id:
            stage.append(index)
        else:
            lost += 1
    return _Assignment(frozenset(keep), tuple(stage), lost)


def _choose(fixed: set[Cell], unbound: tuple[tuple[OpenObligation, tuple[PageIdentity, ...]], ...],
            previous: PageIdentity | None, resident: set[int],
            spilled: set[Cell]) -> _Assignment:
    best: _Assignment | None = None
    best_key: tuple[int, tuple[Cell, ...]] | None = None
    chosen: list[tuple[OpenObligation, PageIdentity]] = []

    def walk(index: int) -> None:
        nonlocal best, best_key
        if index == len(unbound):
            outcome = _evaluate(fixed, tuple(chosen), previous, resident, spilled)
            key = (outcome.required, tuple(sorted(outcome.keep)))
            if best_key is None or key < best_key:
                best_key, best = key, outcome
            return
        obligation, options = unbound[index]
        for page in options:
            chosen.append((obligation, page))
            walk(index + 1)
            chosen.pop()

    walk(0)
    assert best is not None
    return best


def _split(cursors: CursorLedger, in_slot: set[int],
           spilled: set[Cell]) -> tuple[set[Cell], tuple[tuple[OpenObligation, tuple[PageIdentity, ...]], ...]]:
    """Separate fixed obligations from still-complete unbound candidates.

    A choice ticket keeps every candidate that is still complete selectable, but
    stops constraining the write once no candidate can lead a first block.
    """
    fixed: set[Cell] = set()
    unbound: list[tuple[OpenObligation, tuple[PageIdentity, ...]]] = []
    for obligation in cursors.open_obligations():
        if obligation.choice_candidate:
            options = tuple(page for page in obligation.pages
                            if _complete_before(page, obligation, in_slot, spilled))
            if options:
                unbound.append((obligation, options))
        else:
            for page in obligation.pages:
                fixed |= _span_cells(page, obligation)
    return fixed, tuple(unbound)


def plan_overwrite(previous: PageIdentity | None, other: PageIdentity | None,
                   cursors: CursorLedger, spill: SpillStore) -> OverwritePlan:
    capacity = spill.capacity()
    spilled = spill.positions()
    resident = set() if other is None else {other.page_id}
    in_slot = {page.page_id for page in (previous, other) if page is not None}
    fixed, unbound = _split(cursors, in_slot, spilled)
    outcome = _choose(fixed, unbound, previous, resident, spilled)
    return OverwritePlan(outcome.keep, outcome.stage, outcome.required, capacity, outcome.lost)


def plan_retention(cursors: CursorLedger, resident: set[int],
                   spilled: set[Cell]) -> frozenset[Cell]:
    """Spill cells to keep once a read releases its hold.

    Every candidate that is still complete stays complete: its unread cells stay
    in a device slot or the spill store. Ordinary and bound obligations keep
    their whole unread interval.
    """
    in_slot = set(resident)
    keep: set[Cell] = set()
    for obligation in cursors.open_obligations():
        if obligation.choice_candidate:
            for page in obligation.pages:
                if _complete_before(page, obligation, in_slot, spilled):
                    keep |= _span_cells(page, obligation)
        else:
            for page in obligation.pages:
                keep |= _span_cells(page, obligation)
    return frozenset(cell for cell in keep if cell[0] not in resident)


def release_unneeded(cursors: CursorLedger, bank, spill: SpillStore) -> None:
    keep = plan_retention(cursors, bank.resident_page_ids(), spill.positions())
    spill.retain(keep)
