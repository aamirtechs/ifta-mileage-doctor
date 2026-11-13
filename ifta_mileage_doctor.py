"""ifta-mileage-doctor: build an IFTA quarterly return from trip and fuel logs.

Reads a quarterly trip log (miles by state), a fuel purchase log
(gallons by state), and a rates file (tax rate per gallon by state),
and produces an IFTA quarterly return: fleet MPG, taxable gallons
per state, net gallons after tax-paid fuel, and tax due or credit
per state, with a grand total.

Input formats (JSON):

* Trips: a list of {"state": "TX", "miles": 2400} objects, or an
  object with a "trips" list. Multiple entries for one state are
  summed. Miles may be numbers or numeric strings.
* Fuel: a list of {"state": "TX", "gallons": 280} objects, or an
  object with a "fuel" list. Multiple entries for one state are
  summed.
* Rates: an object mapping state codes to rates, {"TX": 0.20}, or
  a list of {"state": "TX", "rate": 0.20} objects, or an object
  with a "rates" key holding either shape.

Rules:

* State codes are two letters, case-insensitive, normalized to
  uppercase. IFTA covers US states and Canadian provinces.
* Fleet MPG is total miles divided by total fuel gallons. Taxable
  gallons per state are state miles divided by the fleet MPG,
  rounded to two decimals. Using the unrounded MPG keeps the
  per-state taxable gallons summing to total fuel gallons.
* Net gallons per state are taxable gallons minus tax-paid gallons
  (fuel bought in that state). A negative net means a credit.
* Tax due per state is net gallons times that state's rate,
  rounded to cents with Decimal. A negative tax due is a credit.
* Money and gallons use Decimal throughout, so float errors never
  leak into a return.
* A state with miles but no rate gets no tax due (shown as n/a).
  With --check that is a failure. A state with fuel purchases but
  no miles is an unaccounted fuel state, and --check fails on it.
* Negative miles, gallons, or rates are bad input (exit 2), as are
  missing files, invalid JSON, wrong shapes, and bad state codes.
* Exit 0 is a report (or a passed check), 1 is a failed --check,
  2 is bad input. Bad input errors go to stderr.

Usage:

    python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json
    python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --quarter 2026-Q3
    python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --json
    python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --check
    python3 ifta_mileage_doctor.py examples/trips.json --fuel examples/fuel.json --rates examples/rates.json --state TX
    cat examples/trips.json | python3 ifta_mileage_doctor.py - --fuel examples/fuel.json --rates examples/rates.json
"""

import argparse
import csv
import io
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__version__ = "1.0.0"

CENT = Decimal("0.01")
GALLON = Decimal("0.01")
MPG_PLACES = Decimal("0.01")


class InputError(ValueError):
    """Raised for any bad input that should exit 2."""


def parse_decimal(value, field, label):
    if isinstance(value, bool):
        raise InputError(f"{label}: {field} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise InputError(f"{label}: {field} is not a valid number: {value!r}")
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise InputError(f"{label}: {field} must not be empty")
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise InputError(f"{label}: {field} is not a valid number: {value!r}")
    else:
        raise InputError(f"{label}: {field} must be a number, got {value!r}")
    return amount


def parse_state(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label}: state must be a two-letter code, got {value!r}")
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise InputError(f"{label}: state must be a two-letter code, got {value!r}")
    return code


def load_json_text(text, label):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{label}: invalid JSON: {exc}")


def extract_list(data, key, label):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and key in data:
        raw_list = data[key]
        if not isinstance(raw_list, list):
            raise InputError(f"{label}: '{key}' must be a list")
        return raw_list
    raise InputError(
        f"{label}: JSON top level must be a list or an object with a '{key}' list")


def load_trips(text):
    data = load_json_text(text, "trips")
    raw_list = extract_list(data, "trips", "trips")
    totals = {}
    for index, raw in enumerate(raw_list):
        label = f"trip {index}"
        if not isinstance(raw, dict):
            raise InputError(f"{label}: each trip must be an object, got {type(raw).__name__}")
        if "state" not in raw:
            raise InputError(f"{label}: missing required field 'state'")
        state = parse_state(raw["state"], label)
        label = f"trip {state} (entry {index})"
        if "miles" not in raw:
            raise InputError(f"{label}: missing required field 'miles'")
        miles = parse_decimal(raw["miles"], "miles", label)
        if miles < 0:
            raise InputError(f"{label}: miles must not be negative: {raw['miles']!r}")
        totals[state] = totals.get(state, Decimal("0")) + miles
    return totals


def load_fuel(text):
    data = load_json_text(text, "fuel")
    raw_list = extract_list(data, "fuel", "fuel")
    totals = {}
    for index, raw in enumerate(raw_list):
        label = f"fuel purchase {index}"
        if not isinstance(raw, dict):
            raise InputError(
                f"{label}: each fuel purchase must be an object, got {type(raw).__name__}")
        if "state" not in raw:
            raise InputError(f"{label}: missing required field 'state'")
        state = parse_state(raw["state"], label)
        label = f"fuel purchase {state} (entry {index})"
        if "gallons" not in raw:
            raise InputError(f"{label}: missing required field 'gallons'")
        gallons = parse_decimal(raw["gallons"], "gallons", label)
        if gallons < 0:
            raise InputError(f"{label}: gallons must not be negative: {raw['gallons']!r}")
        totals[state] = totals.get(state, Decimal("0")) + gallons
    return totals


def load_rates(text):
    data = load_json_text(text, "rates")
    if isinstance(data, dict) and "rates" in data:
        data = data["rates"]
    rates = {}
    if isinstance(data, dict):
        items = data.items()
        for state_raw, rate_raw in items:
            state = parse_state(state_raw, "rates")
            rate = parse_decimal(rate_raw, "rate", f"rate {state}")
            if rate < 0:
                raise InputError(f"rate {state}: rate must not be negative: {rate_raw!r}")
            rates[state] = rate
        return rates
    if isinstance(data, list):
        for index, raw in enumerate(data):
            label = f"rate {index}"
            if not isinstance(raw, dict):
                raise InputError(f"{label}: each rate must be an object, got {type(raw).__name__}")
            if "state" not in raw:
                raise InputError(f"{label}: missing required field 'state'")
            state = parse_state(raw["state"], label)
            label = f"rate {state} (entry {index})"
            if "rate" not in raw:
                raise InputError(f"{label}: missing required field 'rate'")
            rate = parse_decimal(raw["rate"], "rate", label)
            if rate < 0:
                raise InputError(f"{label}: rate must not be negative: {raw['rate']!r}")
            rates[state] = rate
        return rates
    raise InputError(
        "rates: JSON top level must be an object mapping state codes to rates, "
        "a list of rate objects, or an object with a 'rates' key")


def build_return(miles_by_state, gallons_by_state, rates_by_state, quarter=None):
    total_miles = sum(miles_by_state.values(), Decimal("0"))
    total_gallons = sum(gallons_by_state.values(), Decimal("0"))
    if total_miles <= 0:
        raise InputError("cannot compute fleet MPG: total miles is 0")
    if total_gallons <= 0:
        raise InputError("cannot compute fleet MPG: total fuel gallons is 0")
    mpg_exact = total_miles / total_gallons
    mpg = mpg_exact.quantize(MPG_PLACES, rounding=ROUND_HALF_UP)
    states = {}
    grand_total = Decimal("0.00")
    grand_total_known = True
    for state in sorted(set(miles_by_state) | set(gallons_by_state)):
        miles = miles_by_state.get(state, Decimal("0"))
        tax_paid = gallons_by_state.get(state, Decimal("0"))
        taxable = (miles / mpg_exact).quantize(GALLON, rounding=ROUND_HALF_UP)
        net = taxable - tax_paid
        rate = rates_by_state.get(state)
        if rate is None and (miles > 0 or tax_paid > 0):
            tax_due = None
            grand_total_known = False
        elif rate is None:
            tax_due = Decimal("0.00")
        else:
            tax_due = (net * rate).quantize(CENT, rounding=ROUND_HALF_UP)
            grand_total += tax_due
        states[state] = {
            "miles": miles,
            "taxable_gallons": taxable,
            "tax_paid_gallons": tax_paid,
            "net_gallons": net,
            "rate": rate,
            "tax_due": tax_due,
        }
    total_taxable = sum((entry["taxable_gallons"] for entry in states.values()),
                        Decimal("0.00"))
    total_net = sum((entry["net_gallons"] for entry in states.values()),
                    Decimal("0.00"))
    return {
        "quarter": quarter,
        "total_miles": total_miles,
        "total_gallons": total_gallons,
        "fleet_mpg": mpg,
        "fleet_mpg_exact": mpg_exact,
        "states": states,
        "total_taxable_gallons": total_taxable,
        "total_net_gallons": total_net,
        "grand_total_tax": grand_total if grand_total_known else None,
        "missing_rates": sorted(state for state, entry in states.items()
                                if entry["rate"] is None and entry["miles"] > 0),
        "unaccounted_fuel_states": sorted(state for state, entry in states.items()
                                          if entry["miles"] <= 0 and entry["tax_paid_gallons"] > 0),
    }


def money_str(amount):
    return f"{amount:.2f}"


def gallons_str(amount):
    return f"{amount:.2f}"


def format_text(result):
    lines = []
    title = "IFTA quarterly return"
    if result["quarter"]:
        title += f" for {result['quarter']}"
    lines.append(title)
    lines.append("")
    if "fleet_total_miles" in result:
        lines.append(f"Fleet MPG: {money_str(result['fleet_mpg'])} (fleet-wide: "
                     f"{gallons_str(result['fleet_total_miles'])} miles / "
                     f"{gallons_str(result['fleet_total_gallons'])} gallons)")
    else:
        lines.append(f"Fleet MPG: {money_str(result['fleet_mpg'])} "
                     f"({gallons_str(result['total_miles'])} miles / "
                     f"{gallons_str(result['total_gallons'])} gallons)")
    lines.append(f"Total miles: {gallons_str(result['total_miles'])}")
    lines.append(f"Total fuel purchased: {gallons_str(result['total_gallons'])} gallons")
    lines.append("")
    lines.append(f"{'State':<6} {'Miles':>10} {'Taxable gal':>12} {'Tax-paid gal':>13} "
                 f"{'Net gal':>10} {'Rate':>6} {'Tax due':>10}")
    for state in sorted(result["states"]):
        entry = result["states"][state]
        rate = money_str(entry["rate"]) if entry["rate"] is not None else "n/a"
        tax = money_str(entry["tax_due"]) if entry["tax_due"] is not None else "n/a"
        lines.append(f"{state:<6} {gallons_str(entry['miles']):>10} "
                     f"{gallons_str(entry['taxable_gallons']):>12} "
                     f"{gallons_str(entry['tax_paid_gallons']):>13} "
                     f"{gallons_str(entry['net_gallons']):>10} {rate:>6} {tax:>10}")
    lines.append(f"{'Total':<6} {gallons_str(result['total_miles']):>10} "
                 f"{gallons_str(result['total_taxable_gallons']):>12} "
                 f"{gallons_str(result['total_gallons']):>13} "
                 f"{gallons_str(result['total_net_gallons']):>10} {'':>6} "
                 f"{money_str(result['grand_total_tax']) if result['grand_total_tax'] is not None else 'n/a':>10}")
    lines.append("")
    if result["grand_total_tax"] is None:
        unknown = ", ".join(state for state, entry in sorted(result["states"].items())
                            if entry["tax_due"] is None)
        lines.append("Grand total tax due: n/a (tax unknown for: " + unknown + ")")
    elif result["grand_total_tax"] < 0:
        lines.append(f"Grand total tax due: {money_str(result['grand_total_tax'])} "
                     f"(a credit of {money_str(-result['grand_total_tax'])})")
    elif result["grand_total_tax"] == 0:
        lines.append("Grand total tax due: 0.00 (no tax owed)")
    else:
        lines.append(f"Grand total tax due: {money_str(result['grand_total_tax'])}")
    miles_states = sum(1 for entry in result["states"].values() if entry["miles"] > 0)
    fuel_states = sum(1 for entry in result["states"].values()
                      if entry["tax_paid_gallons"] > 0)
    lines.append(f"States: {miles_states} with miles, {fuel_states} with fuel purchases")
    return "\n".join(lines) + "\n"


def return_to_json(result):
    return {
        "quarter": result["quarter"],
        "total_miles": gallons_str(result["total_miles"]),
        "total_gallons": gallons_str(result["total_gallons"]),
        "fleet_mpg": money_str(result["fleet_mpg"]),
        "total_taxable_gallons": gallons_str(result["total_taxable_gallons"]),
        "total_net_gallons": gallons_str(result["total_net_gallons"]),
        "grand_total_tax": (money_str(result["grand_total_tax"])
                            if result["grand_total_tax"] is not None else None),
        "missing_rates": result["missing_rates"],
        "unaccounted_fuel_states": result["unaccounted_fuel_states"],
        "states": {
            state: {
                "miles": gallons_str(entry["miles"]),
                "taxable_gallons": gallons_str(entry["taxable_gallons"]),
                "tax_paid_gallons": gallons_str(entry["tax_paid_gallons"]),
                "net_gallons": gallons_str(entry["net_gallons"]),
                "rate": money_str(entry["rate"]) if entry["rate"] is not None else None,
                "tax_due": (money_str(entry["tax_due"])
                            if entry["tax_due"] is not None else None),
            }
            for state, entry in sorted(result["states"].items())
        },
    }


def format_csv(result):
    """Return a spreadsheet-ready table using the already-computed values."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["state", "miles", "taxable_gallons", "tax_paid_gallons",
                     "net_gallons", "rate", "tax_due"])
    for state, entry in sorted(result["states"].items()):
        writer.writerow([state, gallons_str(entry["miles"]),
                         gallons_str(entry["taxable_gallons"]),
                         gallons_str(entry["tax_paid_gallons"]),
                         gallons_str(entry["net_gallons"]),
                         str(entry["rate"]) if entry["rate"] is not None else "",
                         money_str(entry["tax_due"]) if entry["rate"] is not None
                         and entry["tax_due"] is not None else ""])
    total_tax = result["grand_total_tax"]
    writer.writerow(["Total", gallons_str(result["total_miles"]),
                     gallons_str(result["total_taxable_gallons"]),
                     gallons_str(result["total_gallons"]),
                     gallons_str(result["total_net_gallons"]), "",
                     money_str(total_tax) if total_tax is not None else ""])
    return output.getvalue()


def check_reasons(result):
    reasons = []
    if result["missing_rates"]:
        reasons.append("missing rate for state(s) with miles: "
                       + ", ".join(result["missing_rates"]))
    if result["unaccounted_fuel_states"]:
        reasons.append("fuel purchased in state(s) with no miles: "
                       + ", ".join(result["unaccounted_fuel_states"]))
    return reasons


def read_file(path, label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise InputError(f"cannot read {label} file {path}: {exc.strerror or exc}")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="ifta-mileage-doctor",
        description="Build an IFTA quarterly return from trip, fuel, and rates JSON files.",
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="Trips JSON file path, or '-' / omitted for stdin")
    parser.add_argument("--fuel", required=True,
                        help="Fuel purchases JSON file path (gallons by state)")
    parser.add_argument("--rates", required=True,
                        help="Rates JSON file path (tax rate per gallon by state)")
    parser.add_argument("--quarter", default=None,
                        help="Quarter label for the return, for example 2026-Q3")
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    formats.add_argument("--format", choices=("text", "json", "csv"), default="text",
                         help="Output format (default: text)")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 on a missing rate for a state with miles, "
                             "or on fuel purchased in a state with no miles")
    parser.add_argument("--state", default=None,
                        help="Only show this state in the report (two-letter code)")
    args = parser.parse_args(argv)
    if args.state is not None:
        try:
            args.state = parse_state(args.state, "--state")
        except InputError as exc:
            parser.error(str(exc))
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.input is None or args.input == "-":
            trips_text = sys.stdin.read()
        else:
            trips_text = read_file(args.input, "trips")
        fuel_text = read_file(args.fuel, "fuel")
        rates_text = read_file(args.rates, "rates")
        miles_by_state = load_trips(trips_text)
        gallons_by_state = load_fuel(fuel_text)
        rates_by_state = load_rates(rates_text)
        result = build_return(miles_by_state, gallons_by_state, rates_by_state,
                              quarter=args.quarter)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    display = result
    if args.state is not None:
        if args.state not in result["states"]:
            display = dict(result)
            display["states"] = {}
            display["total_miles"] = Decimal("0.00")
            display["total_gallons"] = Decimal("0.00")
            display["total_taxable_gallons"] = Decimal("0.00")
            display["total_net_gallons"] = Decimal("0.00")
            display["grand_total_tax"] = Decimal("0.00")
            display["missing_rates"] = []
            display["unaccounted_fuel_states"] = []
        else:
            entry = result["states"][args.state]
            display = dict(result)
            display["states"] = {args.state: entry}
            display["fleet_total_miles"] = result["total_miles"]
            display["fleet_total_gallons"] = result["total_gallons"]
            display["total_miles"] = entry["miles"]
            display["total_gallons"] = entry["tax_paid_gallons"]
            display["total_taxable_gallons"] = entry["taxable_gallons"]
            display["total_net_gallons"] = entry["net_gallons"]
            display["grand_total_tax"] = entry["tax_due"]
            display["missing_rates"] = ([args.state] if entry["rate"] is None
                                        and entry["miles"] > 0 else [])
            display["unaccounted_fuel_states"] = (
                [args.state] if entry["miles"] <= 0 and entry["tax_paid_gallons"] > 0 else [])
    json_output = args.json or args.format == "json"
    csv_output = args.format == "csv"
    if json_output:
        print(json.dumps(return_to_json(display), indent=2))
    elif csv_output:
        print(format_csv(display), end="")
    else:
        print(format_text(display), end="")
    if args.check:
        reasons = check_reasons(result)
        if reasons:
            if not json_output:
                print("CHECK FAILED: " + "; ".join(reasons),
                      file=sys.stderr if csv_output else sys.stdout)
            return 1
        if not json_output:
            print("CHECK PASSED: all states with miles have rates, "
                  "no fuel in states with no miles", file=sys.stderr if csv_output else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
