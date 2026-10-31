from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from catalogue.models import Store

DEMO_STORES = [
    {"code": "PUN-01", "name": "Pune Store", "city": "Pune"},
    {"code": "MUM-01", "name": "Mumbai Store", "city": "Mumbai"},
]
SAMPLE_CSV = settings.BASE_DIR / "sample_data" / "pune_catalogue.csv"


class Command(BaseCommand):
    help = "Create the demo stores and import the sample catalogue into PUN-01."

    def handle(self, *args, **options):
        # get_or_create so the command can be run again without failing or duplicating stores.
        for store_data in DEMO_STORES:
            store, created = Store.objects.get_or_create(
                code=store_data["code"],
                defaults={"name": store_data["name"], "city": store_data["city"]},
            )
            status = "created" if created else "already exists"
            self.stdout.write(f"Store {store.code}: {status}")

        call_command("import_catalogue", "PUN-01", str(SAMPLE_CSV), stdout=self.stdout)
