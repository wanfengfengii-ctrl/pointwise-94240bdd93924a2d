import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from device.page_identity import SamplePosition
from device.source_read import SourceReadError
from station.api import Station
from station.samples import SampleRule

UNIT = 'μm'
MISSING = -9999
RULE = SampleRule(Decimal('-100'), Decimal('100'), 3, MISSING)
A = (7, 8, 9, 10)
B = (11, 13, 17, 19)
C = (23, 29, 31, 37)
D = (41, 43, 47, 53)
E = (59, 61, 67, 71)


def samples_in(block):
    return [(sample.position.page.page_id, sample.position.index, sample.value.token)
            for sample in block.samples]


class StationCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'station.sqlite'
        self.reject_next = False
        self.fail_read_at = None
        self.seen_reads = []
        self.station = self.connect_station()
        self.addCleanup(lambda: self.station.close())
        self.profile = self.station.start_shift('day', 'line-2', 4, UNIT, RULE)

    def connect_station(self):
        return Station(self.path, reject_write=self.reject_write, before_read=self.before_read)

    def reopen(self):
        self.station.close()
        self.station = self.connect_station()

    def reject_write(self, target, page):
        if self.reject_next:
            self.reject_next = False
            return True
        return False

    def before_read(self, position):
        self.seen_reads.append(position)
        if position == self.fail_read_at:
            self.fail_read_at = None
            raise SourceReadError(f'fixture could not read {position}')

    def submit(self, values):
        return self.station.capture_page('day', UNIT, enumerate(values))

    def capture(self, values):
        result = self.submit(values)
        self.assertEqual(result.status, 'captured')
        self.assertIsNotNone(result.version)
        return result.version

    def ticket(self, version, start, stop):
        return self.station.open_ticket(version.page, start, stop).ticket_id

    def arm_failed_read(self, version, index):
        self.seen_reads.clear()
        self.fail_read_at = SamplePosition(version.page, index)
