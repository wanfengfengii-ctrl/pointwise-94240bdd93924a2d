import json
import tempfile
from decimal import Decimal
from pathlib import Path

from station.api import Station
from station.samples import SampleRule

UNIT = 'μm'
MISSING = -9999


def submit(station, values):
    return station.capture_page('day', UNIT, enumerate(values))


def capture(station, values):
    result = submit(station, values)
    if result.status != 'captured' or result.version is None:
        raise RuntimeError(f'expected a captured page, got {result!r}')
    return result.version


def originals(station, ticket, maximum):
    block = station.read_next(ticket.ticket_id, maximum)
    return [[sample.position.page.page_id, sample.position.index, sample.value.token]
            for sample in block.samples]


def receipt_body(receipt):
    result = receipt.statement
    return {
        'receipt_id': receipt.receipt_id,
        'valid': result.counts.valid,
        'missing': result.counts.missing,
        'peak': None if result.peak is None else str(result.peak),
        'unit': result.unit.value,
        'origins': [[point.page.page_id, point.index] for point in result.origins],
    }


def emit(case_id, inputs, expected, actual, downstream_expected, downstream_actual,
         code_paths, oracle):
    if actual != expected or downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id}: {actual!r} and {downstream_actual!r}')
    evidence = {
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def main():
    a_values = [7, 8, 9, 10]
    b_values = [11, 13, 17, 19]
    c_values = [23, 29, 31, 37]
    d_values = [41, 43, 47, 53]
    e_values = [MISSING, 0, -9, 4]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'station.sqlite'
        with Station(path) as station:
            station.start_shift('day', 'line-2', 4, UNIT,
                                SampleRule(Decimal('-100'), Decimal('100'), 0, MISSING))
            a = capture(station, a_values)
            a_ticket = station.open_ticket(a.page, 0, 1)
            b = capture(station, b_values)
            left = station.open_ticket(b.page, 0, 3)
            right = station.open_ticket(b.page, 2, 4)
            first = originals(station, left, 1)
            c = capture(station, c_values)
            d = submit(station, d_values)
            c_ticket = station.open_ticket(c.page, 0, 1)
            first_e = submit(station, e_values)
            left_next = originals(station, left, 1)
            second_e = submit(station, e_values)
            rest = {
                'a_ticket': originals(station, a_ticket, 1),
                'left_ticket': left_next + originals(station, left, 1),
                'right_ticket': originals(station, right, 2),
                'c_ticket': originals(station, c_ticket, 1),
            }
            emit('v4', {'pages': [a_values, b_values, c_values, d_values, e_values],
                        'initial_left_read': 1, 'spill_capacity': 4,
                        'ticket_ranges': [[0, 1], [0, 3], [2, 4], [0, 1]]},
                 {'d': 'captured', 'e_attempts': ['pending', 'captured'],
                  'first_left': [[2, 0, 11]]},
                 {'d': d.status, 'e_attempts': [first_e.status, second_e.status],
                  'first_left': first},
                 {'a_ticket': [[1, 0, 7]], 'left_ticket': [[2, 1, 13], [2, 2, 17]],
                  'right_ticket': [[2, 2, 17], [2, 3, 19]], 'c_ticket': [[3, 0, 23]]},
                 rest,
                 ['capture/write_admission.py', 'capture/intake.py', 'capture/source_index.py',
                  'delivery/read_blocks.py'],
                 'A0 and B1–B3 fill four cells. Only B1 is freed by the next left read. Match returned coordinates directly to input arrays.')
            review_ticket = station.open_ticket(second_e.version.page, 0, 4)
            delivered = originals(station, review_ticket, 2) + originals(station, review_ticket, 2)
            receipt = station.finish_review(review_ticket.ticket_id)
            capture(station, a_values)
            capture(station, b_values)
        with Station(path) as reopened:
            stable = reopened.get_receipt(receipt.receipt_id)
        emit('v7', {'original_page': e_values, 'block_limits': [2, 2]},
             [[5, 0, MISSING], [5, 1, 0], [5, 2, -9], [5, 3, 4]], delivered,
             {'receipt_id': 1, 'valid': 3, 'missing': 1, 'peak': '9', 'unit': UNIT,
              'origins': [[5, 0], [5, 1], [5, 2], [5, 3]]}, receipt_body(stable),
             ['delivery/history.py', 'review/counts.py', 'review/peak.py',
              'review/reconcile.py', 'review/receipts.py'],
             'Count 0, -9 and 4 as valid. The largest absolute value is 9. The first signed ticket has receipt 1.')
        if stable != receipt:
            raise AssertionError('reopened receipt changed')


if __name__ == '__main__':
    main()
