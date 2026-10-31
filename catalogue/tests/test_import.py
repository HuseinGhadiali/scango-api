import csv
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from catalogue.importer import (
    ImportFileError,
    RowError,
    clean_active,
    clean_barcode,
    clean_price,
    import_catalogue_file,
)
from catalogue.models import ImportRun, Product

SAMPLE_CSV = settings.BASE_DIR / "sample_data" / "pune_catalogue.csv"


def write_csv(path, header, rows, encoding="utf-8"):
    with open(path, "w", newline="", encoding=encoding) as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerows(rows)
    return path


# --- Single values ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("₹1,299.00", Decimal("1299.00")),
        ("1299", Decimal("1299.00")),
        ("1,299.5", Decimal("1299.50")),
        ("  165.00 ", Decimal("165.00")),
        ("₹ 189.00", Decimal("189.00")),
        ("₹1,29,999.00", Decimal("129999.00")),  # Indian digit grouping
        ("0", Decimal("0.00")),
    ],
)
def test_clean_price_accepts_common_formats(raw, expected):
    assert clean_price(raw) == expected


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("", "missing price"),
        ("   ", "missing price"),
        ("-10.00", "negative price"),
        ("free", "invalid price"),
        ("NaN", "invalid price"),
        ("1e3", "invalid price"),
        ("45.999", "more than 2 decimal places"),
        ("100000000", "too large"),
    ],
)
def test_clean_price_rejects_bad_values(raw, reason):
    with pytest.raises(RowError, match=reason):
        clean_price(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "4006381333931",  # a real EAN-13 with a correct check digit
        "  8900000010011  ",  # surrounding spaces are trimmed
        "40170725",  # 8 digits
        "012345678905",  # 12 digits, leading zero kept
    ],
)
def test_clean_barcode_accepts_valid_codes(raw):
    assert clean_barcode(raw) == raw.strip()


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("", "missing barcode"),
        ("4006381333932", "invalid EAN-13 check digit"),
        ("89012AB345678", "only digits"),
        ("12345", "8, 12 or 13 digits"),
        ("8.90E+12", "only digits"),  # what Excel does to long numbers
    ],
)
def test_clean_barcode_rejects_bad_codes(raw, reason):
    with pytest.raises(RowError, match=reason):
        clean_barcode(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("YES", True), ("1", True), ("", True), ("false", False), ("No", False)],
)
def test_clean_active(raw, expected):
    assert clean_active(raw) is expected


# --- Whole files ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_sample_file_rejects_and_cleans_each_messy_row(store):
    result = import_catalogue_file(store, SAMPLE_CSV)

    assert (result.total, result.created, result.updated, result.unchanged, result.failed) == (
        30, 19, 0, 0, 11,
    )
    reasons = {row_number: reason for row_number, _, reason in result.errors}
    assert reasons == {
        10: "duplicate barcode in file; replaced by row 20",
        21: "invalid EAN-13 check digit",
        22: "missing price",
        23: "missing name",
        24: "negative price",
        25: "barcode must contain only digits",
        26: "barcode must be 8, 12 or 13 digits, got 5",
        27: "invalid price 'free'",
        28: "price has more than 2 decimal places",
        29: "invalid active value 'maybe'",
        30: "missing barcode",
    }

    # Cleaned rows: extra spaces trimmed, rupee prices parsed, last duplicate kept.
    toor_dal = Product.objects.get(store=store, barcode="8900000010073")
    assert (toor_dal.sku, toor_dal.name, toor_dal.price) == ("PUL-001", "Toor Dal 1kg", Decimal("165.00"))
    assert Product.objects.get(store=store, barcode="8900000010042").price == Decimal("1299.00")
    assert Product.objects.get(store=store, barcode="8900000010066").price == Decimal("1299.50")
    assert Product.objects.get(store=store, barcode="8900000010097").price == Decimal("99.00")
    assert Product.objects.get(store=store, barcode="8900000010127").is_active is False


@pytest.mark.django_db
def test_error_report_is_written(store):
    result = import_catalogue_file(store, SAMPLE_CSV)

    with open(result.report_path, encoding="utf-8-sig") as report:
        rows = list(csv.reader(report))
    assert rows[0] == ["row_number", "barcode", "reason"]
    assert rows[1] == ["10", "8900000010097", "duplicate barcode in file; replaced by row 20"]
    assert len(rows) == 1 + result.failed


@pytest.mark.django_db
def test_header_variants_and_bom_are_accepted(store, tmp_path):
    path = write_csv(
        tmp_path / "variants.csv",
        ["  EAN ", "sku", "PRODUCT   NAME", "Price", "ACTIVE"],
        [["40170725", "CON-001", "Chocolate Bar", "40", "yes"]],
        encoding="utf-8-sig",  # writes a BOM
    )

    result = import_catalogue_file(store, path)

    assert result.created == 1
    assert Product.objects.get(store=store, barcode="40170725").name == "Chocolate Bar"


@pytest.mark.django_db
def test_missing_column_rejects_the_file(store, tmp_path):
    path = write_csv(tmp_path / "bad.csv", ["barcode", "name", "price"], [])

    with pytest.raises(ImportFileError, match="missing columns: sku, active"):
        import_catalogue_file(store, path)


@pytest.mark.django_db
def test_dry_run_writes_nothing(store):
    result = import_catalogue_file(store, SAMPLE_CSV, dry_run=True)

    assert result.created == 19  # still counted, so the report is useful
    assert Product.objects.count() == 0
    assert ImportRun.objects.count() == 0


@pytest.mark.django_db
def test_rerunning_the_same_file_creates_nothing_new(store):
    import_catalogue_file(store, SAMPLE_CSV)

    second = import_catalogue_file(store, SAMPLE_CSV)

    assert (second.created, second.updated, second.unchanged) == (0, 0, 19)
    assert Product.objects.count() == 19


@pytest.mark.django_db
def test_changed_rows_are_updated(store, tmp_path):
    header = ["barcode", "sku", "name", "price", "active"]
    first = write_csv(tmp_path / "v1.csv", header, [["40170725", "C1", "Chocolate", "40", "yes"]])
    second = write_csv(tmp_path / "v2.csv", header, [["40170725", "C1", "Chocolate", "45", "yes"]])
    import_catalogue_file(store, first)

    result = import_catalogue_file(store, second)

    assert (result.created, result.updated, result.unchanged) == (0, 1, 0)
    assert Product.objects.get(store=store, barcode="40170725").price == Decimal("45.00")


@pytest.mark.django_db
def test_import_run_is_recorded(store):
    import_catalogue_file(store, SAMPLE_CSV)

    run = ImportRun.objects.get()
    assert run.store == store
    assert run.filename == "pune_catalogue.csv"
    assert (run.total_rows, run.created_count, run.failed_count) == (30, 19, 11)
    assert run.started_at <= run.finished_at


@pytest.mark.django_db
def test_command_prints_summary(store, capsys):
    call_command("import_catalogue", "PUN-01", str(SAMPLE_CSV), "--dry-run")

    output = capsys.readouterr().out
    assert "Dry run: nothing was written to the database." in output
    assert "Total: 30  Created: 19  Updated: 0  Unchanged: 0  Failed: 11" in output


@pytest.mark.django_db
def test_command_unknown_store(db):
    with pytest.raises(CommandError, match="does not exist"):
        call_command("import_catalogue", "XXX-99", str(SAMPLE_CSV))


@pytest.mark.django_db
def test_seed_demo_creates_stores_and_imports(capsys):
    call_command("seed_demo")
    call_command("seed_demo")  # safe to run twice

    assert sorted(ImportRun.objects.values_list("created_count", flat=True)) == [0, 19]
    assert Product.objects.filter(store__code="PUN-01").count() == 19
    assert Product.objects.filter(store__code="MUM-01").count() == 0
