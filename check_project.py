"""Run this project's full unittest suite and the choice-ticket interleavings."""
import sys
import unittest

from choice_scenarios import ChoiceScenarios


def build_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ChoiceScenarios))
    return suite


def main():
    suite = build_suite()
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
