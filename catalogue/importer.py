"""Clean, validate and upsert a store's catalogue from a CSV file.

The import_catalogue management command is a thin wrapper around import_catalogue_file, so this
logic can be tested without going through the command line.
"""

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ImportRun, Product

# Normalised header -> the field it fills. normalise_header() turns "  Product   Name " into
# "product name", so differences in case and spacing don't matter.
HEADER_ALIASES = {
    "barcode": "barcode",
    "ean": "barcode",
    "sku": "sku",
    "name": "name",
    "product name": "name",
    "price": "price",
    "active": "active",
}
REQUIRED_COLUMNS = ["barcode", "sku", "name", "price", "active"]

VALID_BARCODE_LENGTHS = (8, 12, 13)  # EAN-8, UPC-A and EAN-13
# The largest value DecimalField(max_digits=10, decimal_places=2) can hold.
MAX_PRICE = Decimal("99999999.99")
# After removing the rupee sign and commas a price must look like "1299" or "1299.5". A regex is
# used instead of trusting Decimal(), because Decimal() also accepts "NaN", "Infinity" and "1e3".
PRICE_PATTERN = re.compile(r"-?[0-9]+(\.[0-9]+)?")

TRUE_VALUES = {"true", "yes", "y", "1"}
FALSE_VALUES = {"false", "no", "n", "0"}


class ImportFileError(Exception):
    """The whole file is unusable (missing, wrong encoding, missing columns)."""


class RowError(Exception):
    """One row is invalid. It is skipped and the reason goes into the error report."""


@dataclass
class CleanRow:
    row_number: int
    barcode: str
    sku: str
    name: str
    price: Decimal
    is_active: bool


@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list = field(default_factory=list)  # (row_number, barcode, reason) tuples
    report_path: Path | None = None

    @property
    def failed(self):
        return len(self.errors)


# --- Cleaning single values -------------------------------------------------------------------


def normalise_header(header):
    return " ".join(header.split()).lower()


def ean13_check_digit(first_twelve_digits):
    # EAN-13 weights the first 12 digits 1, 3, 1, 3, ... from the left; the check digit is what
    # brings the weighted sum up to the next multiple of 10.
    total = sum(
        int(digit) * (3 if position % 2 else 1)
        for position, digit in enumerate(first_twelve_digits)
    )
    return str((10 - total % 10) % 10)


def clean_barcode(raw):
    barcode = raw.strip()
    if not barcode:
        raise RowError("missing barcode")
    # A regex rather than str.isdigit(), which also accepts characters like "²".
    if not re.fullmatch(r"[0-9]+", barcode):
        raise RowError("barcode must contain only digits")
    if len(barcode) not in VALID_BARCODE_LENGTHS:
        raise RowError(f"barcode must be 8, 12 or 13 digits, got {len(barcode)}")
    if len(barcode) == 13 and barcode[-1] != ean13_check_digit(barcode[:12]):
        raise RowError("invalid EAN-13 check digit")
    return barcode


def clean_price(raw):
    # Commas are removed wherever they are, so both "1,299.00" and the Indian grouping
    # "1,29,999.00" work.
    text = raw.strip().replace("₹", "").replace(",", "").strip()
    if not text:
        raise RowError("missing price")
    if not PRICE_PATTERN.fullmatch(text):
        raise RowError(f"invalid price {raw.strip()!r}")

    price = Decimal(text)
    if price < 0:
        raise RowError("negative price")
    # Reject rather than round: silently changing a price is worse than asking for a fix.
    if price != price.quantize(Decimal("0.01")):
        raise RowError("price has more than 2 decimal places")
    if price > MAX_PRICE:
        raise RowError("price is too large")
    return price.quantize(Decimal("0.01"))


def clean_active(raw):
    text = raw.strip().lower()
    # A blank cell means active, the same default as Product.is_active.
    if text == "" or text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise RowError(f"invalid active value {raw.strip()!r}")


def clean_row(row_number, values):
    """Turn one raw row (field name -> text) into a CleanRow, or raise RowError."""
    barcode = clean_barcode(values["barcode"])
    name = " ".join(values["name"].split())  # also collapses double spaces inside the name
    if not name:
        raise RowError("missing name")
    return CleanRow(
        row_number=row_number,
        barcode=barcode,
        sku=values["sku"].strip(),
        name=name,
        price=clean_price(values["price"]),
        is_active=clean_active(values["active"]),
    )


# --- Reading the file -------------------------------------------------------------------------


def map_headers(fieldnames):
    """Return {header as written in the file: our field name}, or raise ImportFileError."""
    column_map = {}
    for header in fieldnames:
        field_name = HEADER_ALIASES.get(normalise_header(header))
        if field_name is None:
            continue  # extra columns are ignored
        if field_name in column_map.values():
            raise ImportFileError(f"more than one column maps to {field_name!r}")
        column_map[header] = field_name

    missing = [name for name in REQUIRED_COLUMNS if name not in column_map.values()]
    if missing:
        raise ImportFileError(f"missing columns: {', '.join(missing)}")
    return column_map


def read_rows(csv_path):
    """Return a list of (row_number, {field name: raw text}) for every data row."""
    try:
        # "utf-8-sig" strips the byte order mark (BOM) that Excel puts at the start of the file;
        # without it the first header would read "﻿EAN" and not match.
        with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            column_map = map_headers(reader.fieldnames or [])
            rows = []
            for raw_row in reader:
                # `or ""` because DictReader gives None for cells missing at the end of a row.
                values = {
                    field_name: raw_row.get(header) or ""
                    for header, field_name in column_map.items()
                }
                # line_num is the file's line number (header = 1), which matches the row a
                # person sees in a spreadsheet, even when blank lines are skipped.
                rows.append((reader.line_num, values))
            return rows
    except FileNotFoundError:
        raise ImportFileError(f"file not found: {csv_path}")
    except UnicodeDecodeError:
        raise ImportFileError("file is not UTF-8; save it as 'CSV UTF-8' and try again")


def drop_earlier_duplicates(clean_rows, errors):
    """Keep the last valid row for each barcode and report the earlier ones as errors."""
    latest_by_barcode = {}
    for row in clean_rows:
        earlier = latest_by_barcode.get(row.barcode)
        if earlier is not None:
            errors.append(
                (
                    earlier.row_number,
                    earlier.barcode,
                    f"duplicate barcode in file; replaced by row {row.row_number}",
                )
            )
        latest_by_barcode[row.barcode] = row
    return list(latest_by_barcode.values())


# --- Writing to the database ------------------------------------------------------------------


def has_changed(product, row):
    return (
        product.sku != row.sku
        or product.name != row.name
        or product.price != row.price
        or product.is_active != row.is_active
    )


def plan_changes(store, clean_rows, result):
    """Split the rows into products to create and products to update, and count the rest."""
    # Load the whole store catalogue once instead of one query per row.
    existing = {product.barcode: product for product in store.products.all()}
    now = timezone.now()
    to_create = []
    to_update = []

    for row in clean_rows:
        product = existing.get(row.barcode)
        if product is None:
            to_create.append(
                Product(
                    store=store,
                    barcode=row.barcode,
                    sku=row.sku,
                    name=row.name,
                    price=row.price,
                    is_active=row.is_active,
                )
            )
        elif has_changed(product, row):
            product.sku = row.sku
            product.name = row.name
            product.price = row.price
            product.is_active = row.is_active
            # bulk_update() skips auto_now, so updated_at has to be set by hand.
            product.updated_at = now
            to_update.append(product)
        else:
            result.unchanged += 1

    result.created = len(to_create)
    result.updated = len(to_update)
    return to_create, to_update


def write_error_report(store, errors, started_at, dry_run, report_dir):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_dry_run" if dry_run else ""
    report_path = report_dir / f"import_{store.code}_{started_at:%Y%m%d_%H%M%S}{suffix}.csv"

    # "utf-8-sig" adds a BOM so Excel shows characters like "₹" correctly.
    with open(report_path, "w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.writer(report_file)
        writer.writerow(["row_number", "barcode", "reason"])
        writer.writerows(errors)
    return report_path


def import_catalogue_file(store, csv_path, dry_run=False, report_dir=None):
    """Import csv_path into store's catalogue and return an ImportResult.

    With dry_run=True every row is validated and counted, and the error report is written,
    but nothing is written to the database.
    """
    started_at = timezone.now()
    csv_path = Path(csv_path)
    result = ImportResult()

    raw_rows = read_rows(csv_path)
    result.total = len(raw_rows)

    clean_rows = []
    for row_number, values in raw_rows:
        try:
            clean_rows.append(clean_row(row_number, values))
        except RowError as error:
            result.errors.append((row_number, values["barcode"].strip(), str(error)))
    clean_rows = drop_earlier_duplicates(clean_rows, result.errors)

    # One transaction: either the whole file is applied or none of it is, so a crash halfway
    # never leaves the catalogue half-updated.
    with transaction.atomic():
        to_create, to_update = plan_changes(store, clean_rows, result)
        if not dry_run:
            Product.objects.bulk_create(to_create)
            Product.objects.bulk_update(
                to_update, ["sku", "name", "price", "is_active", "updated_at"]
            )
            ImportRun.objects.create(
                store=store,
                filename=csv_path.name,
                total_rows=result.total,
                created_count=result.created,
                updated_count=result.updated,
                unchanged_count=result.unchanged,
                failed_count=result.failed,
                started_at=started_at,
                finished_at=timezone.now(),
            )

    result.errors.sort()
    result.report_path = write_error_report(
        store, result.errors, started_at, dry_run, report_dir or settings.IMPORT_REPORT_DIR
    )
    return result
