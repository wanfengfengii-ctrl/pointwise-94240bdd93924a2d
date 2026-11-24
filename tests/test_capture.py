from decimal import Decimal

from device.page_identity import PageIdentity
from device.source_read import SourceReadError
from station.probes import ProbeProfile
from station.samples import SampleRule
from station.units import MeasurementUnit
from tests.fixtures import A, B, C, D, MISSING, RULE, UNIT, StationCase, samples_in


class TestCapture(StationCase):
    def test_cyclic_slots(self):
        versions = [self.capture(values) for values in (A, B, C)]
        self.assertEqual([(entry.slot, entry.generation, entry.page.page_id) for entry in versions],
                         [(0, 1, 1), (1, 1, 2), (0, 2, 3)])
        self.assertIsNone(self.station.device_source.current_source(versions[0].page))
        self.assertEqual(self.station.order.next_target().slot, 1)
        self.assertEqual(self.station.spill.used(), 0)

    def test_shift_rules(self):
        with self.assertRaises(ValueError):
            self.station.start_shift('other', 'absent', 4, UNIT, RULE)
        with self.assertRaises(ValueError):
            self.station.start_shift('other', 'line-2', 5, UNIT, RULE)
        with self.assertRaises(ValueError):
            self.station.start_shift('other', 'line-2', 4, 'mm', RULE)
        with self.assertRaises(ValueError):
            self.station.start_shift('day', 'line-2', 3, UNIT, RULE)
        self.assertEqual(self.station.start_shift('day', 'line-2', 4, UNIT, RULE), self.profile)
        self.assertEqual(self.capture(A).page, PageIdentity(1))

    def test_reinitialize(self):
        modified_rule = SampleRule(Decimal('-5'), Decimal('5'), 0, MISSING)
        modified = ProbeProfile('line-2', MeasurementUnit.MICROMETRE, 2, modified_rule)
        self.station.register_probe(modified)
        a = self.capture(A)
        old_ticket = self.ticket(a, 0, 1)
        b = self.capture(B)
        self.reopen()
        self.station.initialize()
        self.assertEqual(self.station.probes.require('line-2'), modified)
        self.assertEqual(self.station.start_shift('day', 'line-2', 4, UNIT, RULE), self.profile)
        with self.assertRaises(ValueError):
            self.station.start_shift('other', 'line-2', 4, UNIT, RULE)
        new_shift = self.station.start_shift('other', 'line-2', 2, UNIT, modified_rule)
        self.assertEqual(new_shift.page_length, 2)
        after = self.capture(C)
        self.assertEqual((after.slot, after.generation, after.page.page_id), (0, 2, 3))
        self.assertEqual(self.station.bank.get_slot(1).version, b)
        self.assertEqual(self.station.spill.used(), 1)
        self.assertEqual(samples_in(self.station.read_next(old_ticket, 1)), [(1, 0, 7)])

    def test_bad_page_size(self):
        before = self.station.order.next_target()
        with self.assertRaisesRegex(ValueError, 'expected 4 samples'):
            self.submit((7, 8, 9))
        self.assertEqual(self.station.order.next_target(), before)
        self.assertIsNone(self.station.bank.get_slot(before.slot))
        result = self.capture(A)
        self.assertEqual((result.slot, result.page), (before.slot, before.page))

    def test_page_contract(self):
        before = self.station.order.next_target()
        cases = [
            ('mm', list(enumerate(A))),
            (UNIT, [(0, 7), (1, 8), (1, 9), (3, 10)]),
            (UNIT, [(0, 7), (2, 9), (1, 8), (3, 10)]),
            (UNIT, list(enumerate([7, 101, 9, 10]))),
            (UNIT, list(enumerate([7, '8.0001', 9, 10]))),
            (UNIT, list(enumerate([True, 8, 9, 10]))),
        ]
        for unit, samples in cases:
            with self.subTest(unit=unit, samples=samples):
                with self.assertRaises(ValueError):
                    self.station.capture_page('day', unit, samples)
                self.assertEqual(self.station.order.next_target(), before)
                self.assertIsNone(self.station.intake.pending_request())
        result = self.capture((MISSING, 0, -9, '+4.000'))
        self.assertEqual(result.page, before.page)
        ticket = self.ticket(result, 0, 4)
        self.assertEqual(samples_in(self.station.read_next(ticket, 4)),
                         [(1, 0, MISSING), (1, 1, 0), (1, 2, -9), (1, 3, '+4.000')])

    def test_device_write_failure(self):
        a = self.capture(A)
        a_ticket = self.ticket(a, 0, 1)
        b = self.capture(B)
        b_ticket = self.ticket(b, 1, 4)
        self.capture(C)
        before = self.station.order.next_target()
        self.reject_next = True
        result = self.submit(D)
        self.assertEqual((result.status, result.target, result.required), ('device_failed', before, 4))
        self.assertIsNone(result.version)
        self.assertIsNone(self.station.intake.pending_request())
        self.assertEqual(self.station.spill.used(), 1)
        self.assertEqual(self.station.order.next_target(), before)
        self.assertEqual(self.station.bank.get_slot(b.slot).version, b)
        self.assertEqual(samples_in(self.station.read_next(b_ticket, 1)), [(2, 1, 13)])
        retry = self.capture(D)
        self.assertEqual((retry.slot, retry.page, retry.generation), (before.slot, before.page, 2))
        self.assertEqual(self.station.spill.used(), 3)
        self.assertEqual(samples_in(self.station.read_next(b_ticket, 4)), [(2, 2, 17), (2, 3, 19)])
        self.assertEqual(samples_in(self.station.read_next(a_ticket, 1)), [(1, 0, 7)])
        self.assertEqual(self.station.spill.used(), 0)

    def test_preservation_read_failure(self):
        a = self.capture(A)
        ticket = self.ticket(a, 0, 2)
        self.capture(B)
        before = self.station.order.next_target()
        self.arm_failed_read(a, 1)
        with self.assertRaises(SourceReadError):
            self.submit(C)
        self.assertEqual([point.index for point in self.seen_reads], [0, 1])
        self.assertEqual(self.station.spill.used(), 0)
        self.assertEqual(self.station.order.next_target(), before)
        self.assertEqual(self.station.bank.get_slot(a.slot).version, a)
        self.assertEqual(self.capture(C).page, before.page)
        self.assertEqual(samples_in(self.station.read_next(ticket, 4)), [(1, 0, 7), (1, 1, 8)])
