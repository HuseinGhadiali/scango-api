"""Fixtures shared by every test file. pytest finds this file automatically."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalogue.models import Product, Store


@pytest.fixture(autouse=True)
def import_reports_in_tmp(settings, tmp_path):
    # Keep error reports written by tests out of the project's reports/ folder.
    settings.IMPORT_REPORT_DIR = tmp_path / "reports"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def store(db):
    return Store.objects.create(code="PUN-01", name="Pune Store", city="Pune")


@pytest.fixture
def other_store(db):
    return Store.objects.create(code="MUM-01", name="Mumbai Store", city="Mumbai")


@pytest.fixture
def product(store):
    return Product.objects.create(
        store=store,
        barcode="8900000010011",
        sku="DAI-001",
        name="Salted Butter 500g",
        price=Decimal("275.00"),
    )
