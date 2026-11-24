import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


class StationStore:
    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')

    def initialize(self, *initializers: Callable[[], None]) -> None:
        with self.transaction():
            for initialize in initializers:
                initialize()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def close(self) -> None:
        self.db.close()
