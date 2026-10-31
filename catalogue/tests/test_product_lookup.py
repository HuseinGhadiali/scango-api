from decimal import Decimal

import pytest

from catalogue.models import Product

pytestmark = pytest.mark.django_db


def product_url(store_code, barcode):
    return f"/api/stores/{store_code}/products/{barcode}/"


def test_store_list(api_client, store, other_store):
    response = api_client.get("/api/stores/")

    assert response.status_code == 200
    assert [s["code"] for s in response.json()] == ["MUM-01", "PUN-01"]


def test_product_found(api_client, product):
    response = api_client.get(product_url("PUN-01", product.barcode))

    assert response.status_code == 200
    assert response.json() == {
        "barcode": "8900000010011",
        "sku": "DAI-001",
        "name": "Salted Butter 500g",
        "price": "275.00",  # a string, so no float rounding
    }


def test_product_in_another_store_is_404(api_client, product, other_store):
    response = api_client.get(product_url("MUM-01", product.barcode))

    assert response.status_code == 404


def test_unknown_store_is_404(api_client, product):
    response = api_client.get(product_url("XXX-99", product.barcode))

    assert response.status_code == 404


def test_inactive_product_is_404(api_client, product):
    product.is_active = False
    product.save()

    response = api_client.get(product_url("PUN-01", product.barcode))

    assert response.status_code == 404


def test_same_barcode_in_two_stores_has_its_own_price(api_client, product, other_store):
    Product.objects.create(
        store=other_store,
        barcode=product.barcode,
        sku="DAI-001",
        name="Salted Butter 500g",
        price=Decimal("280.00"),
    )

    assert api_client.get(product_url("PUN-01", product.barcode)).json()["price"] == "275.00"
    assert api_client.get(product_url("MUM-01", product.barcode)).json()["price"] == "280.00"


def test_product_list_hides_inactive_and_searches(api_client, store, product):
    Product.objects.create(
        store=store, barcode="40170725", sku="CON-001", name="Chocolate Bar", price="40.00"
    )
    Product.objects.create(
        store=store,
        barcode="012345678905",
        sku="OLD-001",
        name="Discontinued Butter",
        price="10.00",
        is_active=False,
    )

    all_active = api_client.get("/api/stores/PUN-01/products/").json()
    searched = api_client.get("/api/stores/PUN-01/products/?search=butter").json()

    assert all_active["count"] == 2
    assert [p["name"] for p in searched["results"]] == ["Salted Butter 500g"]


def test_product_list_is_paginated_by_20(api_client, store):
    for number in range(25):
        Product.objects.create(
            store=store, barcode=f"{number:08d}", sku=f"S{number}", name=f"Item {number}", price="1.00"
        )

    first_page = api_client.get("/api/stores/PUN-01/products/").json()

    assert first_page["count"] == 25
    assert len(first_page["results"]) == 20
    assert first_page["next"] is not None


def test_product_list_unknown_store_is_404(api_client, db):
    assert api_client.get("/api/stores/XXX-99/products/").status_code == 404
