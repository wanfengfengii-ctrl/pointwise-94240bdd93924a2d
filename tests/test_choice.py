from decimal import Decimal

from delivery.closeout import IncompleteTicketError
from device.page_identity import PageIdentity, SamplePosition
from device.source_read import SourceReadError
from station.api import Station
from tests.fixtures import A, B, C, D, E, MISSING, RULE, UNIT, StationCase, samples_in


class TestChoiceContract(StationCase):
    def connect_station(self):
        return Station(self.path, spill_capacity=2, reject_write=self.reject_write,
                       before_read=self.before_read)

    def opened(self, start=0, stop=2):
        a, b = self.capture(A), self.capture(B)
        choice = self.station.open_choice_ticket(a.page, b.page, start, stop)
        return a, b, choice

    def read(self, ticket, maximum, page):
        return samples_in(self.station.read_choice(ticket, maximum, page))

    def test_open_rejects_bad_identity_and_interval(self):
        a = self.capture(A)
        b = self.capture(B)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, a.page, 0, 2)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, 'not-a-page', 0, 2)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, b.page, 0, 5)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, b.page, 0, 0)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, b.page, True, 2)
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, b.page, 0.0, 2)
        self.capture(C)
        # A is no longer current after C overwrites its slot
        with self.assertRaises(LookupError):
            self.station.open_choice_ticket(a.page, b.page, 0, 2)

    def test_cross_shift_pair_is_rejected(self):
        self.station.start_shift('night', 'line-2', 4, UNIT, RULE)
        a = self.station.capture_page('day', UNIT, enumerate(A)).version
        b = self.station.capture_page('night', UNIT, enumerate(B)).version
        with self.assertRaises(ValueError):
            self.station.open_choice_ticket(a.page, b.page, 0, 2)

    def test_ordinary_entry_rejects_choice_ticket(self):
        _, _, choice = self.opened()
        with self.assertRaises(LookupError):
            self.station.read_next(choice, 1)
        with self.assertRaises(LookupError):
            self.station.finish_review(choice)

    def test_choice_entry_rejects_ordinary_ticket(self):
        a, _, _ = self.opened()
        ordinary = self.station.open_ticket(a.page, 0, 2).ticket_id
        with self.assertRaises(LookupError):
            self.station.read_choice(ordinary, 1, a.page)

    def test_read_parameters_are_validated_before_binding(self):
        _, _, choice = self.opened()
        self.capture(C)
        for bad in (0, -3, True, 1.5):
            with self.subTest(maximum=bad), self.assertRaises(ValueError):
                self.station.read_choice(choice, bad, PageIdentity(1))
        with self.assertRaises(ValueError):
            self.station.read_choice(choice, 1, 'page')
        with self.assertRaises(ValueError):
            self.station.read_choice(choice, 1, PageIdentity(3))
        # nothing bound after rejected calls
        self.assertEqual(self.read(choice, 2, PageIdentity(2)), [(2, 0, 11), (2, 1, 13)])
        with self.assertRaises(ValueError):
            self.read(choice, 1, PageIdentity(1))

    def test_first_block_needs_every_position_intact(self):
        a, b = self.capture(A), self.capture(B)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 3)
        self.capture(C)
        # C overwrites A's slot; no ticket required A, so nothing is spilled and
        # A is no longer a usable candidate. B survives untouched in its slot.
        self.assertEqual(self.station.spill.used(), 0)
        with self.assertRaises(ValueError):
            self.read(choice, 2, a.page)
        self.assertEqual(self.read(choice, 3, b.page), [(2, 0, 11), (2, 1, 13), (2, 2, 17)])

    def test_partial_candidate_cannot_lead(self):
        a, b = self.capture(A), self.capture(B)
        ordinary_a = self.station.open_ticket(a.page, 0, 2).ticket_id
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 3)
        self.capture(C)
        # Only A0/A1 were required by the ordinary ticket; A2 is gone.
        self.assertEqual(self.station.spill.used(), 2)
        self.station.read_next(ordinary_a, 2)
        self.reopen()
        with self.assertRaises(ValueError):
            self.read(choice, 1, a.page)
        self.assertEqual(self.read(choice, 3, b.page), [(2, 0, 11), (2, 1, 13), (2, 2, 17)])

    def test_exhausted_ticket_keeps_its_page(self):
        a, b = self.capture(A), self.capture(B)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        ordinary_a = self.station.open_ticket(a.page, 0, 2).ticket_id
        self.capture(C)
        self.assertEqual(self.read(choice, 2, a.page), [(1, 0, 7), (1, 1, 8)])
        self.assertEqual(self.read(choice, 2, a.page), [])
        with self.assertRaises(ValueError):
            self.read(choice, 1, b.page)
        self.assertEqual(samples_in(self.station.read_next(ordinary_a, 2)),
                         [(1, 0, 7), (1, 1, 8)])

    def test_other_ticket_consumption_keeps_candidate_selectable(self):
        a, b, choice = self.opened()
        self.capture(C)
        ordinary_b = self.station.open_ticket(b.page, 0, 2).ticket_id
        self.station.read_next(ordinary_b, 2)
        self.assertEqual(self.read(choice, 2, b.page), [(2, 0, 11), (2, 1, 13)])
        receipt = self.station.finish_choice(choice)
        self.assertEqual(receipt.statement.page, b.page)

    def test_pending_retry_keeps_candidates(self):
        a, b, choice = self.opened()
        ordinary_a = self.station.open_ticket(a.page, 0, 2).ticket_id
        ordinary_b = self.station.open_ticket(b.page, 0, 2).ticket_id
        self.capture(C)
        first = self.submit(D)
        self.assertEqual((first.status, first.required, first.capacity), ('pending', 4, 2))
        self.reopen()
        # Both A and B are still complete candidates while D waits.
        self.assertEqual(self.read(choice, 2, a.page), [(1, 0, 7), (1, 1, 8)])
        self.assertEqual(samples_in(self.station.read_next(ordinary_b, 2)),
                         [(2, 0, 11), (2, 1, 13)])
        accepted = self.capture(D)
        self.assertEqual(accepted.page.page_id, 4)
        self.assertEqual(samples_in(self.station.read_next(ordinary_a, 2)),
                         [(1, 0, 7), (1, 1, 8)])

    def test_device_failure_keeps_candidates(self):
        a, b, choice = self.opened()
        self.station.open_ticket(a.page, 0, 2)
        self.capture(C)
        self.reject_next = True
        failed = self.submit(D)
        self.assertEqual(failed.status, 'device_failed')
        self.reopen()
        self.assertEqual(self.read(choice, 2, a.page), [(1, 0, 7), (1, 1, 8)])
        accepted = self.capture(D)
        self.assertEqual(accepted.page.page_id, 4)

    def test_shared_positions_keep_spill_single_cell(self):
        a, b, choice = self.opened()
        ordinary_a = self.station.open_ticket(a.page, 0, 2).ticket_id
        self.capture(C)
        self.assertEqual(self.station.spill.used(), 2)
        self.station.read_next(ordinary_a, 1)
        self.assertEqual(self.station.spill.used(), 2)
        self.station.read_next(ordinary_a, 1)
        # A0 shared by ordinary A and the choice ticket; A1 only by A0's
        # ordinary consumer was released, but A1 stays for the unread choice.
        self.assertIsNotNone(self.station.spill.fetch(SamplePosition(a.page, 0)))
        self.assertIsNotNone(self.station.spill.fetch(SamplePosition(a.page, 1)))
        self.assertEqual(self.read(choice, 2, a.page), [(1, 0, 7), (1, 1, 8)])
        self.assertEqual(self.station.spill.used(), 0)

    def test_receipt_uses_bound_page_after_reopen(self):
        a, b, choice = self.opened()
        self.capture(C)
        self.assertEqual(self.read(choice, 2, b.page), [(2, 0, 11), (2, 1, 13)])
        self.reopen()
        receipt = self.station.finish_choice(choice)
        self.assertEqual(receipt.statement.page, b.page)
        self.assertEqual(receipt.statement.peak, Decimal('13'))
        self.reopen()
        self.assertEqual(self.station.get_receipt(receipt.receipt_id), receipt)
        self.assertEqual(self.station.finish_choice(choice), receipt)

    def test_all_missing_choice_peak_is_none(self):
        a = self.capture((MISSING,) * 4)
        b = self.capture((MISSING,) * 4)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        self.assertEqual(self.read(choice, 2, b.page), [(2, 0, MISSING), (2, 1, MISSING)])
        receipt = self.station.finish_choice(choice)
        self.assertIsNone(receipt.statement.peak)
        self.assertEqual((receipt.statement.counts.valid, receipt.statement.counts.missing), (0, 2))

    def test_incomplete_choice_has_no_receipt(self):
        _, _, choice = self.opened()
        self.capture(C)
        with self.assertRaises(IncompleteTicketError):
            self.station.finish_choice(choice)
        self.assertEqual(self.read(choice, 1, PageIdentity(2)), [(2, 0, 11)])
        with self.assertRaises(IncompleteTicketError):
            self.station.finish_choice(choice)
        self.assertIsNone(self.station.receipts.find_by_ticket(choice))

    def test_later_read_failure_keeps_bound_progress(self):
        a, b, choice = self.opened()
        self.capture(C)
        self.assertEqual(self.read(choice, 1, b.page), [(2, 0, 11)])
        self.arm_failed_read(b, 1)
        with self.assertRaises(SourceReadError):
            self.read(choice, 1, b.page)
        self.assertEqual(len(self.station.journal.for_ticket(choice)), 1)
        self.assertEqual(ChoiceState.bound_page(self.station, choice), b.page)
        self.assertEqual(self.read(choice, 1, b.page), [(2, 1, 13)])
        receipt = self.station.finish_choice(choice)
        self.assertEqual(receipt.statement.peak, Decimal('13'))

    def test_capture_exchanges_spill_for_the_still_complete_candidate(self):
        a, b, choice = self.opened()
        ordinary_a = self.station.open_ticket(a.page, 0, 2).ticket_id
        self.capture(C)
        self.assertEqual(self.station.spill.used(), 2)
        # D wants B's slot. A is still a complete candidate, so the two cells
        # hold A0/A1 and D is admitted without touching B's samples.
        accepted = self.capture(D)
        self.assertEqual(accepted.page.page_id, 4)
        self.assertEqual(self.station.spill.used(), 2)
        self.assertEqual(self.read(choice, 2, a.page), [(1, 0, 7), (1, 1, 8)])
        with self.assertRaises(ValueError):
            self.read(choice, 1, b.page)
        self.assertEqual(samples_in(self.station.read_next(ordinary_a, 2)),
                         [(1, 0, 7), (1, 1, 8)])
        self.assertEqual(self.station.spill.used(), 0)


class ChoiceState:
    @staticmethod
    def bound_page(station, ticket):
        row = station.tickets.choice_row(ticket)
        return None if row['bound_page_id'] is None else PageIdentity(row['bound_page_id'])


class TestChoiceRobustness(StationCase):
    def connect_station(self):
        return Station(self.path, spill_capacity=2, reject_write=self.reject_write,
                       before_read=self.before_read)

    def test_ticket_with_no_complete_candidate_never_wedges_capture(self):
        a, b = self.capture(A), self.capture(B)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        # No ticket requires A0/A1; overwriting A drops them from both slot and
        # spill, so A is dead and B remains the only usable candidate.
        self.capture(C)
        self.assertIsNone(self.station.spill.fetch(SamplePosition(a.page, 0)))
        self.capture(D)
        with self.assertRaises(ValueError):
            self.station.read_choice(choice, 1, a.page)
        self.assertEqual(samples_in(self.station.read_choice(choice, 2, b.page)),
                         [(2, 0, 11), (2, 1, 13)])
        receipt = self.station.finish_choice(choice)
        self.assertEqual(receipt.statement.page, b.page)

    def test_surviving_candidate_can_finish_after_many_overwrites(self):
        a, b = self.capture(A), self.capture(B)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        # The planner is free to drop A and keep B; B's two cells then travel
        # through spill as C, D and E overwrite both slots in turn.
        self.capture(C)
        self.capture(D)
        self.capture(E)
        with self.assertRaises(ValueError):
            self.station.read_choice(choice, 1, a.page)
        self.assertEqual(samples_in(self.station.read_choice(choice, 2, b.page)),
                         [(2, 0, 11), (2, 1, 13)])
        receipt = self.station.finish_choice(choice)
        self.assertEqual(receipt.statement.page, b.page)
        self.assertEqual(self.station.order.next_target().page.page_id, 6)
