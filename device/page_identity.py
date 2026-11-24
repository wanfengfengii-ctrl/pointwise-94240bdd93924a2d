from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class PageIdentity:
    page_id: int

    def __post_init__(self) -> None:
        if type(self.page_id) is not int or not 1 <= self.page_id < 2**63:
            raise ValueError('invalid original page id')


@dataclass(frozen=True, order=True)
class SamplePosition:
    page: PageIdentity
    index: int


@dataclass(frozen=True)
class SlotVersion:
    slot: int
    generation: int
    page: PageIdentity
