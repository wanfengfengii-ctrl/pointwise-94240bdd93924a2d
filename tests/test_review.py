from decimal import Decimal, localcontext

from delivery.closeout import IncompleteTicketError
from tests.fixtures import A, B, C, D, MISSING, StationCase, samples_in


class TestReview(StationCase):
    def assert_statement(self, receipt, expected_counts, peak, origins):
        statement = receipt.statement
        self.assertEqual((statement.counts.valid, statement.counts.missing), expected_counts)
        self.assertEqual(statement.counts.total, len(origins))
        self.assertEqual(statement.peak, peak)
        self.assertEqual(statement.unit, 'μm')
        self.assertEqual([(point.page.page_id, point.index) for point in statement.origins], origins)

    def test_receipt_with_missing(self):
        a = self.capture((MISSING, 0, -9, 4))
        ticket = self.ticket(a, 0, 4)
        self.assertEqual(samples_in(self.station.read_next(ticket, 2)), [(1, 0, MISSING), (1, 1, 0)])
        self.assertEqual(samples_in(self.station.read_next(ticket, 2)), [(1, 2, -9), (1, 3, 4)])
        first = self.station.finish_review(ticket)
        self.assert_statement(first, (3, 1), Decimal('9'), [(1, 0), (1, 1), (1, 2), (1, 3)])
        b = self.capture(B)
        self.capture(C)
        other_ticket = self.ticket(b, 2, 4)
        self.assertEqual(samples_in(self.station.read_next(other_ticket, 9)), [(2, 2, 17), (2, 3, 19)])
        second = self.station.finish_review(other_ticket)
        self.assertNotEqual(first.receipt_id, second.receipt_id)
        self.assert_statement(second, (2, 0), Decimal('19'), [(2, 2), (2, 3)])
        self.capture(D)
        self.reopen()
        for expected in (first, second, first, second):
            self.assertEqual(self.station.get_receipt(expected.receipt_id), expected)
        self.assertEqual(self.station.finish_review(ticket), first)
        with self.assertRaises(LookupError):
            self.station.get_receipt(second.receipt_id + 100)

    def test_all_missing(self):
        a = self.capture((MISSING,) * 4)
        ticket = self.ticket(a, 1, 4)
        self.assertEqual(samples_in(self.station.read_next(ticket, 7)),
                         [(1, 1, MISSING), (1, 2, MISSING), (1, 3, MISSING)])
        receipt = self.station.finish_review(ticket)
        self.assert_statement(receipt, (0, 3), None, [(1, 1), (1, 2), (1, 3)])
        self.capture(B)
        self.capture(C)
        self.reopen()
        self.assertEqual(self.station.get_receipt(receipt.receipt_id), receipt)

    def test_incomplete_ticket_has_no_receipt(self):
        a = self.capture(A)
        ticket = self.ticket(a, 1, 4)
        self.assertEqual(samples_in(self.station.read_next(ticket, 1)), [(1, 1, 8)])
        with self.assertRaises(IncompleteTicketError):
            self.station.finish_review(ticket)
        self.assertIsNone(self.station.receipts.find_by_ticket(ticket))
        with self.assertRaises(LookupError):
            self.station.get_receipt(1)
        self.assertEqual(samples_in(self.station.read_next(ticket, 9)), [(1, 2, 9), (1, 3, 10)])
        receipt = self.station.finish_review(ticket)
        self.assert_statement(receipt, (3, 0), Decimal('10'), [(1, 1), (1, 2), (1, 3)])
        self.assertEqual(self.station.get_receipt(receipt.receipt_id), receipt)

    def test_decimal_peak_is_exact_across_blocks(self):
        a = self.capture(('+0.005', '-9.120', '9.119', 0))
        ticket = self.ticket(a, 0, 4)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(samples_in(self.station.read_next(ticket, 2)),
                             [(1, 0, '+0.005'), (1, 1, '-9.120')])
            self.station.read_next(ticket, 2)
            receipt = self.station.finish_review(ticket)
        self.assert_statement(receipt, (4, 0), Decimal('9.120'), [(1, 0), (1, 1), (1, 2), (1, 3)])
        self.assertEqual(str(receipt.statement.peak), '9.120')
