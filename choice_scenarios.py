import json
import sys
import unittest
from decimal import Decimal

from delivery.closeout import IncompleteTicketError
from device.source_read import SourceReadError
from station.api import Station
from tests.fixtures import A, B, C, D, RULE, UNIT, StationCase, samples_in


def legacy():
    check = unittest.TestCase()
    with Station(":memory:", spill_capacity=2) as station:
        station.start_shift("day", "line-2", 4, UNIT, RULE)

        def submit(values):
            return station.capture_page("day", UNIT, enumerate(values))

        a, b = (submit(values).version.page for values in (A, B))
        ordinary_a = station.open_ticket(a, 0, 2).ticket_id
        ordinary_b = station.open_ticket(b, 0, 2).ticket_id
        check.assertEqual(submit(C).status, "captured")
        both = submit(D)
        check.assertEqual((both.status, both.required, both.capacity), ("pending", 4, 2))
        check.assertEqual(samples_in(station.read_next(ordinary_b, 1)), [(2, 0, 11)])
        after_b = submit(D)
        check.assertEqual((after_b.status, after_b.required), ("pending", 3))
        check.assertEqual(samples_in(station.read_next(ordinary_a, 1)), [(1, 0, 7)])
        retry = submit(D)
        check.assertEqual((retry.status, retry.target), ("captured", both.target))
        tail = samples_in(station.read_next(ordinary_b, 1))
        check.assertEqual(tail, [(2, 1, 13)])
        print(json.dumps({"case": "ordinary_tickets", "attempts": [both.status, after_b.status,
                          retry.status], "required": [both.required, after_b.required,
                          retry.required], "b_tail": tail}))

    with Station(":memory:", spill_capacity=2) as station:
        station.start_shift("day", "line-2", 4, UNIT, RULE)
        a = station.capture_page("day", UNIT, enumerate(A)).version.page
        station.capture_page("day", UNIT, enumerate(B))
        ticket = station.open_ticket(a, 0, 2).ticket_id
        check.assertEqual(station.capture_page("day", UNIT, enumerate(C)).status, "captured")
        check.assertEqual(samples_in(station.read_next(ticket, 2)), [(1, 0, 7), (1, 1, 8)])
        with check.assertRaises(SourceReadError):
            station.source.read_positions(a, range(2))
        check.assertEqual(station.spill.used(), 0)
        print(json.dumps({"case": "ordinary_last_consumer", "retained_a_points": station.spill.used()}))


class ChoiceScenarios(StationCase):
    def connect_station(self):
        return Station(self.path, spill_capacity=2, reject_write=self.reject_write,
                       before_read=self.before_read)

    def opened(self):
        a, b = self.capture(A), self.capture(B)
        ordinary_a = self.ticket(a, 0, 2)
        choice = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        return a, b, ordinary_a, choice

    def read_choice(self, ticket, maximum, page):
        return samples_in(self.station.read_choice(ticket, maximum, page.page))

    def check_receipt(self, choice, page, peak):
        receipt = self.station.finish_choice(choice)
        statement = receipt.statement
        self.assertEqual(statement.page, page.page)
        self.assertEqual([(point.page, point.index) for point in statement.origins],
                         [(page.page, 0), (page.page, 1)])
        self.assertEqual((statement.counts.valid, statement.counts.missing), (2, 0))
        self.assertEqual((statement.unit, statement.peak), (UNIT, Decimal(peak)))
        self.reopen()
        self.assertEqual(self.station.get_receipt(receipt.receipt_id), receipt)
        self.assertEqual(self.station.finish_choice(choice), receipt)

    def test_unread_choice_can_survive_on_a(self):
        a, b, _, choice = self.opened()
        self.capture(C)
        self.capture(D)
        self.reopen()
        with self.assertRaises(ValueError):
            self.read_choice(choice, 2, b)
        self.assertEqual(self.read_choice(choice, 2, a), [(1, 0, 7), (1, 1, 8)])
        self.check_receipt(choice, a, "8")

    def test_first_block_makes_b_tail_mandatory(self):
        a, b, ordinary_a, choice = self.opened()
        self.capture(C)
        self.assertEqual(self.read_choice(choice, 1, b), [(2, 0, 11)])
        pending = self.submit(D)
        self.assertEqual(pending.status, "pending")
        self.reopen()
        with self.assertRaises(ValueError):
            self.read_choice(choice, 1, a)
        self.assertEqual(samples_in(self.station.read_next(ordinary_a, 1)), [(1, 0, 7)])
        self.assertEqual(self.capture(D).page, pending.target.page)
        self.assertEqual(self.read_choice(choice, 1, b), [(2, 1, 13)])
        self.check_receipt(choice, b, "13")

    def test_old_spill_can_be_exchanged_only_on_success(self):
        a, b, ordinary_a, choice = self.opened()
        witness = self.station.open_choice_ticket(a.page, b.page, 0, 2)
        self.capture(C)
        ordinary_b = self.ticket(b, 0, 2)
        self.station.read_next(ordinary_a, 2)
        self.reject_next = True
        self.assertEqual(self.submit(D).status, "device_failed")
        self.assertEqual(self.read_choice(witness, 2, a), [(1, 0, 7), (1, 1, 8)])
        self.assertEqual(self.capture(D).page.page_id, 4)
        with self.assertRaises(ValueError):
            self.read_choice(choice, 2, a)
        self.assertEqual(samples_in(self.station.read_next(ordinary_b, 2)), [(2, 0, 11), (2, 1, 13)])
        self.assertEqual(self.read_choice(choice, 2, b), [(2, 0, 11), (2, 1, 13)])
        self.check_receipt(choice, b, "13")

    def test_first_read_failure_does_not_bind(self):
        a, b, _, choice = self.opened()
        self.capture(C)
        with self.assertRaises(LookupError):
            self.station.read_next(choice, 1)
        self.arm_failed_read(b, 1)
        with self.assertRaises(SourceReadError):
            self.read_choice(choice, 2, b)
        with self.assertRaises(IncompleteTicketError):
            self.station.finish_choice(choice)
        self.reopen()
        self.assertEqual(self.read_choice(choice, 2, a), [(1, 0, 7), (1, 1, 8)])
        self.check_receipt(choice, a, "8")

    def test_candidates_must_fit_together(self):
        a, b, ordinary_a, first = self.opened()
        second = self.station.open_choice_ticket(a.page, b.page, 1, 3)
        self.capture(C)
        self.station.read_next(ordinary_a, 2)
        self.assertEqual(self.submit(D).status, "pending")
        with self.assertRaises(ValueError):
            self.read_choice(second, 1, a)
        self.assertEqual(self.read_choice(first, 2, a), [(1, 0, 7), (1, 1, 8)])
        self.capture(D)
        self.assertEqual(self.read_choice(second, 2, b), [(2, 1, 13), (2, 2, 17)])


if __name__ == "__main__":
    mode = sys.argv[1:2]
    if mode == ["--legacy"]:
        legacy()
    elif mode == ["--choice"]:
        unittest.main(argv=[sys.argv[0], *sys.argv[2:]], verbosity=2)
    else:
        raise SystemExit("usage: python3 -B choice_scenarios.py --legacy|--choice")
