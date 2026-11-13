"""CLI CSV contract, including existing output compatibility."""

import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent
HEADER = ['state', 'miles', 'taxable_gallons', 'tax_paid_gallons',
          'net_gallons', 'rate', 'tax_due']


class TestCsvOutput(unittest.TestCase):
    def cli(self, *args, missing=False):
        return subprocess.run(
            [sys.executable, 'ifta_mileage_doctor.py', 'examples/trips.json',
             '--fuel', 'examples/fuel.json', '--rates',
             'examples/rates-missing.json' if missing else 'examples/rates.json', *args],
            cwd=ROOT, text=True, capture_output=True, check=False)

    def test_shape_order_and_exact_values(self):
        result = self.cli('--format', 'csv')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        rows = list(csv.reader(io.StringIO(result.stdout)))
        self.assertEqual(rows[0], HEADER)
        self.assertEqual([r[0] for r in rows[1:]], ['AZ', 'NM', 'OK', 'TX', 'Total'])
        self.assertTrue(all(len(r) == 7 for r in rows))
        self.assertEqual(rows[1], ['AZ', '600.00', '75.00', '90.00', '-15.00', '0.26', '-3.90'])
        self.assertEqual(rows[-1], ['Total', '4800.00', '600.00', '600.00', '0.00', '', '-0.55'])

    def test_missing_rate_and_total_remain_unknown(self):
        result = self.cli('--format', 'csv', missing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        self.assertEqual(rows[0]['rate'], '')
        self.assertEqual(rows[0]['tax_due'], '')
        self.assertEqual(rows[-1]['tax_due'], '')

    def test_state_filter_recomputes_display_total(self):
        result = self.cli('--format', 'csv', '--state', 'TX')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.reader(io.StringIO(result.stdout)))
        self.assertEqual([r[0] for r in rows[1:]], ['TX', 'Total'])
        self.assertEqual(rows[-1], ['Total', '2400.00', '300.00', '280.00', '20.00', '', '4.00'])

    def test_zero_activity_missing_rate_and_precise_rate(self):
        sys.path.insert(0, str(ROOT))
        from ifta_mileage_doctor import build_return, format_csv

        result = build_return({'TX': Decimal('100'), 'AZ': Decimal('0')},
                              {'TX': Decimal('10')}, {'TX': Decimal('0.2345')})
        rows = list(csv.DictReader(io.StringIO(format_csv(result))))
        self.assertEqual((rows[0]['rate'], rows[0]['tax_due']), ('', ''))
        self.assertEqual(rows[1]['rate'], '0.2345')

    def test_check_keeps_csv_clean_and_preserves_failure_even_when_filtered(self):
        for missing, code, message in [(False, 0, 'CHECK PASSED'), (True, 1, 'CHECK FAILED')]:
            with self.subTest(missing=missing):
                result = self.cli('--format', 'csv', '--check', '--state', 'TX', missing=missing)
                self.assertEqual(result.returncode, code)
                self.assertIn(message, result.stderr)
                rows = list(csv.reader(io.StringIO(result.stdout)))
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(len(r) == 7 for r in rows))
                self.assertNotIn('CHECK', result.stdout)

    def test_invalid_format_and_conflicting_flags_exit_two(self):
        for args in [('--format', 'xml'), ('--json', '--format', 'csv')]:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn('--format', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_explicit_text_and_json_match_legacy_output(self):
        for legacy, explicit in [((), ('--format', 'text')), (('--json',), ('--format', 'json'))]:
            with self.subTest(legacy=legacy):
                old, new = self.cli(*legacy), self.cli(*explicit)
                self.assertEqual((new.returncode, new.stdout, new.stderr),
                                 (old.returncode, old.stdout, old.stderr))
        self.assertEqual(json.loads(self.cli('--json').stdout)['grand_total_tax'], '-0.55')


if __name__ == '__main__':
    unittest.main()
