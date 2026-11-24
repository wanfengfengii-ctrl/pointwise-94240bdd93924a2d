from device.page_identity import SamplePosition
from device.source_read import SourceReadError
from tests.fixtures import A, B, C, D, E, StationCase, samples_in


HANDOFF_FAILURE = 'OVERWRITE_HANDOFF_MISMATCH'


class TestHandoff(StationCase):
    def prepare_overlap(self):
        a = self.capture(A)
        a_ticket = self.ticket(a, 0, 1)
        b = self.capture(B)
        left = self.ticket(b, 0, 3)
        right = self.ticket(b, 2, 4)
        self.assertEqual(samples_in(self.station.read_next(left, 1)), [(2, 0, 11)])
        c = self.capture(C)
        self.assertEqual(self.station.spill.used(), 1)
        return a, b, c, a_ticket, left, right

    def admit_d(self):
        result = self.submit(D)
        self.assertEqual(result.status, 'captured', f'{HANDOFF_FAILURE}: D={result!r}')
        self.assertEqual((result.target.slot, result.required, result.capacity), (1, 4, 4),
                         HANDOFF_FAILURE)
        self.assertEqual(self.station.spill.used(), 4, HANDOFF_FAILURE)
        return result.version

    def assert_original(self, ticket_id, limit, expected):
        try:
            result = self.station.read_next(ticket_id, limit)
        except SourceReadError as error:
            self.fail(f'{HANDOFF_FAILURE}: ticket {ticket_id} expected {expected}, got {error}')
        self.assertEqual(samples_in(result), expected, HANDOFF_FAILURE)
        return result

    def test_shared_remaining_positions(self):
        a, b, _, a_ticket, left, right = self.prepare_overlap()
        d = self.admit_d()
        with self.assertRaises(LookupError):
            self.station.open_ticket(b.page, 0, 1)
        self.assertEqual(self.station.bank.get_slot(b.slot).version, d)
        for point in [SamplePosition(a.page, 0), *(SamplePosition(b.page, n) for n in (1, 2, 3))]:
            self.assertIsNotNone(self.station.spill.fetch(point), HANDOFF_FAILURE)
        self.assertIsNone(self.station.spill.fetch(SamplePosition(b.page, 0)))
        self.assert_original(a_ticket, 10, [(1, 0, 7)])
        self.assert_original(left, 10, [(2, 1, 13), (2, 2, 17)])
        self.assertEqual(self.station.spill.used(), 2)
        self.assert_original(right, 10, [(2, 2, 17), (2, 3, 19)])
        self.assertEqual(self.station.spill.used(), 0)
        self.assert_original(left, 10, [])
        self.assertEqual(len(self.station.journal.for_ticket(left)), 2)

    def test_half_open_intervals(self):
        _, b, _, _, left, right = self.prepare_overlap()
        for start, stop in [(-1, 2), (1, 1), (3, 2), (0, 5), (True, 3)]:
            with self.subTest(start=start, stop=stop), self.assertRaises(ValueError):
                self.station.open_ticket(b.page, start, stop)
        self.admit_d()
        block = self.assert_original(left, 20, [(2, 1, 13), (2, 2, 17)])
        self.assertEqual((block.start, block.stop), (1, 3))
        self.assert_original(right, 20, [(2, 2, 17), (2, 3, 19)])
        empty = self.station.read_next(right, 1)
        self.assertEqual((empty.start, empty.stop, empty.samples), (4, 4, ()))
        self.assertEqual(len(self.station.journal.for_ticket(right)), 1)

    def test_overwritten_source_without_capacity_pressure(self):
        self.capture(A)
        b = self.capture(B)
        ticket = self.ticket(b, 1, 3)
        self.capture(C)
        d = self.capture(D)
        self.assertEqual((d.slot, d.generation), (b.slot, b.generation + 1))
        self.assert_original(ticket, 4, [(2, 1, 13), (2, 2, 17)])
        with self.assertRaises(SourceReadError):
            self.station.device_source.read_positions(b, (1,))
        current = self.ticket(d, 1, 3)
        self.assert_original(current, 4, [(4, 1, 43), (4, 2, 47)])

    def test_resume_after_last_consumer(self):
        _, b, c, a_ticket, left, right = self.prepare_overlap()
        self.admit_d()
        c_ticket = self.ticket(c, 0, 1)
        result = self.submit(E)
        self.assertEqual((result.status, result.required, result.capacity), ('pending', 5, 4))
        self.assertIsNone(result.version)
        request = self.station.intake.pending_request()
        self.assertEqual(request.target, result.target)
        self.assertEqual(self.station.order.next_target(), result.target)
        self.assertEqual(self.station.bank.get_slot(c.slot).version, c)
        self.reopen()
        self.assertEqual(self.station.intake.pending_request(), request)
        self.assertEqual(self.station.spill.used(), 4)
        with self.assertRaises(ValueError):
            self.submit((59, 61, 67, 72))
        self.assertEqual(self.station.intake.pending_request(), request)
        self.assert_original(left, 1, [(2, 1, 13)])
        self.assertIsNone(self.station.spill.fetch(SamplePosition(b.page, 1)))
        self.assertEqual(self.station.spill.used(), 3)
        accepted = self.submit(E)
        self.assertEqual((accepted.status, accepted.target, accepted.required),
                         ('captured', result.target, 4))
        self.assertIsNone(self.station.intake.pending_request())
        self.assert_original(left, 1, [(2, 2, 17)])
        self.assertIsNotNone(self.station.spill.fetch(SamplePosition(b.page, 2)))
        self.assert_original(right, 5, [(2, 2, 17), (2, 3, 19)])
        self.assert_original(a_ticket, 1, [(1, 0, 7)])
        self.assert_original(c_ticket, 1, [(3, 0, 23)])
        self.assertEqual(self.station.spill.used(), 0)

    def test_failed_read_keeps_protection(self):
        _, b, c, _, left, right = self.prepare_overlap()
        self.admit_d()
        self.ticket(c, 0, 1)
        first = self.submit(E)
        self.assertEqual(first.status, 'pending')
        evidence = self.station.journal.for_ticket(left)
        self.assertEqual(len(evidence), 1)
        for index, limit, attempted in [(1, 1, [1]), (2, 2, [1, 2])]:
            self.arm_failed_read(b, index)
            with self.assertRaises(SourceReadError):
                self.station.read_next(left, limit)
            self.assertEqual(self.seen_reads, [SamplePosition(b.page, n) for n in attempted])
            self.assertEqual(self.station.journal.for_ticket(left), evidence)
            self.assertEqual(self.station.tickets.get(left).next_position, 1)
            self.assertEqual(self.station.spill.used(), 4)
            self.assertEqual(self.submit(E), first)
        self.assert_original(left, 1, [(2, 1, 13)])
        self.assertEqual(self.submit(E).status, 'captured')
        self.assert_original(left, 2, [(2, 2, 17)])
        self.assert_original(right, 2, [(2, 2, 17), (2, 3, 19)])

    def test_bad_request_does_not_consume(self):
        a = self.capture(A)
        ticket = self.ticket(a, 1, 3)
        for invalid in (0, -1, True, 1.5):
            with self.subTest(max_samples=invalid), self.assertRaises(ValueError):
                self.station.read_next(ticket, invalid)
        with self.assertRaises(LookupError):
            self.station.read_next(ticket + 100, 1)
        self.assertEqual(self.station.journal.for_ticket(ticket), ())
        self.assert_original(ticket, 1, [(1, 1, 8)])
