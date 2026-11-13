# ifta-mileage-doctor
**Live tool:** https://aamirtechs.github.io/ifta-mileage-doctor/ (runs in your browser, no install)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/ifta-mileage-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/ifta-mileage-doctor/issues)

A zero-dependency Python CLI that turns a quarterly trip log (miles
by state), a fuel purchase log (gallons by state), and a rates file
into an IFTA quarterly return, offline. It computes fleet MPG,
taxable gallons per state, net gallons after tax-paid fuel, and tax
due or credit per state, and doubles as a CI gate with `--check`.

Every interstate carrier files an IFTA return each quarter, and
small fleets still do it in a spreadsheet by hand, 4 to 8 hours of
copying miles and gallons per quarter. This tool reads the three
logs, does the division with Decimal arithmetic, and prints the
same return every time.

## Install

Requires Python 3.10 or newer. No dependencies beyond the standard library.

```bash
pip install ifta-mileage-doctor
```

Or run it straight from the source checkout:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json
```

It also runs as a module:

```bash
python3 -m ifta_mileage_doctor examples/trips.json --fuel examples/fuel.json --rates examples/rates.json
```

## Input format

Three JSON files. Trips and fuel accept a list, or an object with a
`trips` or `fuel` list. Rates accept an object mapping state codes
to rates, a list of rate objects, or an object with a `rates` key
holding either shape. Multiple entries for one state are summed.
Miles, gallons, and rates may be numbers or numeric strings.

Trips (`examples/trips.json`):

```json
[
  {"state": "TX", "miles": 2400},
  {"state": "OK", "miles": 1200},
  {"state": "NM", "miles": 600},
  {"state": "AZ", "miles": 600}
]
```

Fuel (`examples/fuel.json`):

```json
[
  {"state": "TX", "gallons": 280},
  {"state": "OK", "gallons": 170},
  {"state": "NM", "gallons": 60},
  {"state": "AZ", "gallons": 90}
]
```

Rates (`examples/rates.json`, dollars per gallon):

```json
{"TX": 0.20, "OK": 0.19, "NM": 0.21, "AZ": 0.26}
```

State codes are two letters, case-insensitive, normalized to
uppercase. IFTA covers US states and Canadian provinces. The sample
rates are example rates only: always use the current published IFTA
rate for each jurisdiction for the quarter you file.

## The math

* Fleet MPG is total miles divided by total fuel gallons.
* Taxable gallons per state are state miles divided by fleet MPG,
  rounded to two decimals. The unrounded MPG is used for the
  division, so per-state taxable gallons sum exactly to total fuel
  gallons. The displayed MPG is rounded to two decimals.
* Net gallons per state are taxable gallons minus tax-paid gallons
  (fuel bought in that state). A negative net means a credit.
* Tax due per state is net gallons times that state's rate, rounded
  to cents. A negative tax due is a credit, and the grand total is
  the sum of per-state tax due.
* A state with miles but no rate gets no tax due (shown as `n/a`),
  and the grand total is `n/a` until the rate is supplied. A state
  with fuel but no miles still counts as tax-paid fuel for that
  state, and `--check` flags it as unaccounted.

## Usage

Build a return:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json
```

Label the quarter:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3
```

Read trips from stdin (omit the argument, or pass `-`):

```bash
cat examples/trips.json | python3 ifta_mileage_doctor.py - --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3
```

Gate a job on it (exit 1 on a missing rate for a state with miles,
or on fuel purchased in a state with no miles, else exit 0):

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --check
```

Emit JSON instead of text:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3 --json
```

Export the state table as CSV for a spreadsheet:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --format csv > return.csv
```

The CSV includes a header, sorted state rows and a final total row. Missing
rates and unknown tax amounts are empty, including the total when any tax
amount is unknown. With `--check`, the CSV stays on stdout and the check
message goes to stderr; the usual check exit status still applies. `--state`
filters the displayed rows and total, while checks still use the full return.

Show one state only (fleet MPG stays fleet-wide, since taxable
gallons are computed from it):

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3 --state TX
```

## Captured output: the sample return

The sample quarter has 4800 miles across TX, OK, NM, and AZ, and
600 gallons of fuel. Fleet MPG is exactly 8.00, so taxable gallons
are TX 300.00, OK 150.00, NM 75.00, AZ 75.00. Net gallons are TX
20.00, OK -20.00, NM 15.00, AZ -15.00, and the grand total is a
0.55 credit.

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3
```

Captured output:

```
IFTA quarterly return for 2026-Q3

Fleet MPG: 8.00 (4800.00 miles / 600.00 gallons)
Total miles: 4800.00
Total fuel purchased: 600.00 gallons

State       Miles  Taxable gal  Tax-paid gal    Net gal   Rate    Tax due
AZ         600.00        75.00         90.00     -15.00   0.26      -3.90
NM         600.00        75.00         60.00      15.00   0.21       3.15
OK        1200.00       150.00        170.00     -20.00   0.19      -3.80
TX        2400.00       300.00        280.00      20.00   0.20       4.00
Total     4800.00       600.00        600.00       0.00             -0.55

Grand total tax due: -0.55 (a credit of 0.55)
States: 4 with miles, 4 with fuel purchases
```

## Captured output: --check

The sample return is clean, so the gate passes:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3 --check
```

Captured output (exit code 0, last line only shown here):

```
CHECK PASSED: all states with miles have rates, no fuel in states with no miles
```

With `examples/rates-missing.json`, which has no AZ rate, the gate
fails and the AZ tax due is unknown:

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates-missing.json --quarter 2026-Q3 --check
```

Captured output (exit code 1, report above plus this last line):

```
CHECK FAILED: missing rate for state(s) with miles: AZ
```

The AZ row in that report reads:

```
AZ         600.00        75.00         90.00     -15.00    n/a        n/a
```

And the grand total line reads:

```
Grand total tax due: n/a (tax unknown for: AZ)
```

With `examples/fuel-unaccounted.json`, which adds 40 gallons bought
in WY where no miles were driven, the gate fails on the unaccounted
fuel state (fleet MPG drops to 7.50 on 640 gallons, and WY shows
`n/a` tax due because the rates file has no WY rate):

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel-unaccounted.json --rates examples/rates.json --quarter 2026-Q3 --check
```

Captured output (exit code 1, last line only shown here):

```
CHECK FAILED: fuel purchased in state(s) with no miles: WY
```

## Captured output: --state

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3 --state TX
```

Captured output:

```
IFTA quarterly return for 2026-Q3

Fleet MPG: 8.00 (fleet-wide: 4800.00 miles / 600.00 gallons)
Total miles: 2400.00
Total fuel purchased: 280.00 gallons

State       Miles  Taxable gal  Tax-paid gal    Net gal   Rate    Tax due
TX        2400.00       300.00        280.00      20.00   0.20       4.00
Total     2400.00       300.00        280.00      20.00              4.00

Grand total tax due: 4.00
States: 1 with miles, 1 with fuel purchases
```

## Captured output: --json

```bash
python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3 --json
```

Captured output:

```
{
  "quarter": "2026-Q3",
  "total_miles": "4800.00",
  "total_gallons": "600.00",
  "fleet_mpg": "8.00",
  "total_taxable_gallons": "600.00",
  "total_net_gallons": "0.00",
  "grand_total_tax": "-0.55",
  "missing_rates": [],
  "unaccounted_fuel_states": [],
  "states": {
    "AZ": {
      "miles": "600.00",
      "taxable_gallons": "75.00",
      "tax_paid_gallons": "90.00",
      "net_gallons": "-15.00",
      "rate": "0.26",
      "tax_due": "-3.90"
    },
    "NM": {
      "miles": "600.00",
      "taxable_gallons": "75.00",
      "tax_paid_gallons": "60.00",
      "net_gallons": "15.00",
      "rate": "0.21",
      "tax_due": "3.15"
    },
    "OK": {
      "miles": "1200.00",
      "taxable_gallons": "150.00",
      "tax_paid_gallons": "170.00",
      "net_gallons": "-20.00",
      "rate": "0.19",
      "tax_due": "-3.80"
    },
    "TX": {
      "miles": "2400.00",
      "taxable_gallons": "300.00",
      "tax_paid_gallons": "280.00",
      "net_gallons": "20.00",
      "rate": "0.20",
      "tax_due": "4.00"
    }
  }
}
```

With a missing rate, the JSON carries `null` for that state's rate
and tax due, `null` for the grand total, and the state in
`missing_rates`.

## Captured output: bad input

`examples/invalid.json` has negative miles:

```bash
python3 ifta_mileage_doctor.py examples/invalid.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3
```

Captured output on stderr (exit code 2):

```
error: trip TX (entry 0): miles must not be negative: -50
```

## Options

| Flag | Meaning |
| --- | --- |
| `input` | Trips JSON file path, or `-` / omitted for stdin |
| `--fuel` | Fuel purchases JSON file path (required) |
| `--rates` | Rates JSON file path (required) |
| `--quarter` | Quarter label for the return, for example 2026-Q3 |
| `--json` | Emit JSON instead of text |
| `--format` | Select `text` (default), `json`, or `csv`; cannot be combined with `--json` |
| `--check` | Exit 1 on a missing rate for a state with miles, or on fuel purchased in a state with no miles; else exit 0 |
| `--state` | Only show this state (two-letter code) |

Exit codes: 0 for a report (or a passed check), 1 for a failed
`--check`, 2 for bad input (missing file, invalid JSON, wrong shape,
negative miles, gallons, or rates, bad state codes, or zero total
miles or fuel). Bad input errors go to stderr. `--check` looks at
the full return, so a `--state` filter does not hide a failure.

## Edge cases

* Miles, gallons, and money are Decimal, so values like 0.10 and
  0.20 add up to exactly 0.30.
* When fleet MPG is not exact (for example 5000 miles over 600
  gallons, displayed as 8.33), taxable gallons are computed from
  the unrounded MPG and rounded to two decimals, so they still sum
  to total fuel gallons.
* Multiple trip or fuel entries for one state are summed before any
  math runs. Lowercase state codes are normalized to uppercase.
* A state with miles but no rate shows `n/a` tax due and makes the
  grand total `n/a`; it is a `--check` failure, not a silent zero.
* A state with fuel but no miles shows zero taxable gallons and a
  negative net (a credit in gallons); `--check` flags it.
* Zero total miles or zero total fuel is an error, because fleet
  MPG cannot be computed.
* State codes must be exactly two letters. `TEXAS` and `T1` are
  rejected with the entry in the error message.

## Tests

```bash
python3 -m pytest tests/ -q
python3 -m unittest discover -s tests -v
```

37 tests, all passing: the sample return (fleet MPG, taxable and
net gallons, tax due, and grand total), non-exact MPG math,
Decimal cents math, duplicate state summing, lowercase state
normalization, the list and object input shapes, missing-rate and
unaccounted-fuel check failures, validation errors for negative
miles, gallons, and rates, bad state codes, missing fields, invalid
JSON, wrong top level shape, and zero total miles or fuel, plus CLI
tests for text and JSON output, `--check` pass and fail, `--state`
filter, stdin trips, module run, and exit code 2 for bad input,
missing files, a missing `--rates` flag, and a bad `--state` value.

## License

MIT. See [LICENSE](LICENSE).
