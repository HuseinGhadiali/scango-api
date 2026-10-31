from django.core.management.base import BaseCommand, CommandError

from catalogue.importer import ImportFileError, import_catalogue_file
from catalogue.models import Store


class Command(BaseCommand):
    help = "Import a store's catalogue from a CSV file (barcode, sku, name, price, active)."

    def add_arguments(self, parser):
        parser.add_argument("store_code")
        parser.add_argument("csv_path")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report, but write nothing to the database.",
        )

    def handle(self, *args, **options):
        store_code = options["store_code"]
        try:
            store = Store.objects.get(code=store_code)
        except Store.DoesNotExist:
            raise CommandError(f"Store {store_code!r} does not exist.")

        try:
            result = import_catalogue_file(
                store, options["csv_path"], dry_run=options["dry_run"]
            )
        except ImportFileError as error:
            raise CommandError(str(error))

        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was written to the database.")
        self.stdout.write(
            f"Total: {result.total}  Created: {result.created}  Updated: {result.updated}  "
            f"Unchanged: {result.unchanged}  Failed: {result.failed}"
        )
        self.stdout.write(f"Error report: {result.report_path}")
