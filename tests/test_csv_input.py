"""CSV files share the existing trip/fuel validation and calculation path."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class CsvInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def file(self, name, content):
        path = self.directory / name
        path.write_text(content, encoding='utf-8')
        return str(path)

    def cli(self, trips, fuel, *args, stdin=None):
        return subprocess.run([sys.executable, 'ifta_mileage_doctor.py', trips,
                               '--fuel', fuel, '--rates', 'examples/rates.json', *args],
                              cwd=ROOT, text=True, input=stdin, capture_output=True, check=False)

    def test_csv_matches_json_with_mixed_formats_and_uppercase_extension(self):
        trips = self.file('TRIPS.CSV', '\ufeffstate,miles\nTX,2400\nOK,1200\nNM,600\nAZ,600\n')
        fuel = self.file('fuel.csv', 'state,gallons\nTX,280\nOK,170\nNM,60\nAZ,90\n')
        expected = self.cli('examples/trips.json', 'examples/fuel.json', '--json')
        self.assertEqual(expected.returncode, 0)
        for a, b in [(trips, fuel), (trips, 'examples/fuel.json'), ('examples/trips.json', fuel)]:
            with self.subTest(trips=a, fuel=b):
                result = self.cli(a, b, '--json')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), json.loads(expected.stdout))

    def test_bad_state_and_empty_trips_exit_two(self):
        for content, reason in [('state,miles\nTEXAS,100\n', 'two-letter code'),
                                ('state,miles\n', 'total miles is 0')]:
            with self.subTest(content=content):
                result = self.cli(self.file('bad.csv', content), 'examples/fuel.json')
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)

    def test_malformed_header_and_rows_are_reported(self):
        for content, reason in [('state,distance\nTX,20\n', 'missing required column'),
                                ('state,state,miles\nTX,TX,20\n', 'unique column'),
                                ('state,miles\nTX,20,extra\n', 'extra fields'),
                                ('state,miles\n"TX,20\n', 'invalid CSV')]:
            with self.subTest(content=content):
                result = self.cli(self.file('bad.csv', content), 'examples/fuel.json')
                self.assertEqual(result.returncode, 2)
                self.assertIn(reason, result.stderr)

    def test_csv_fuel_errors_and_json_stdin(self):
        trips = (ROOT / 'examples/trips.json').read_text(encoding='utf-8')
        bad_fuel = self.file('fuel.csv', 'state,gallons\nTX,-1\n')
        result = self.cli('-', bad_fuel, stdin=trips)
        self.assertEqual(result.returncode, 2)
        self.assertIn('gallons must not be negative', result.stderr)
        good = self.file('fuel.csv', 'state,gallons\nTX,280\nOK,170\nNM,60\nAZ,90\n')
        self.assertEqual(self.cli('-', good, stdin=trips).returncode, 0)


if __name__ == '__main__':
    unittest.main()
