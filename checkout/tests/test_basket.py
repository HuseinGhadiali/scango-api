from decimal import Decimal

import pytest

from catalogue.models import Product
from checkout.models import Basket

pytestmark = pytest.mark.django_db


def add_item(api_client, basket, barcode, quantity=1):
    return api_client.post(
        f"/api/baskets/{basket.id}/items/",
        {"barcode": barcode, "quantity": quantity},
        format="json",
    )


def test_create_basket(api_client, store):
    response = api_client.post("/api/baskets/", {"store_code": "PUN-01"}, format="json")

    assert response.status_code == 201
    assert response.json()["status"] == "open"
    assert Basket.objects.get().store == store


def test_create_basket_unknown_store(api_client, db):
    response = api_client.post("/api/baskets/", {"store_code": "XXX-99"}, format="json")

    assert response.status_code == 400


def test_price_snapshot_survives_a_later_price_change(api_client, basket, product):
    add_item(api_client, basket, product.barcode, quantity=2)

    product.price = Decimal("999.00")
    product.save()
    response = api_client.get(f"/api/baskets/{basket.id}/")

    line = response.json()["items"][0]
    assert line["unit_price"] == "275.00"
    assert line["line_total"] == "550.00"
    assert response.json()["subtotal"] == "550.00"


def test_adding_twice_increments_quantity(api_client, basket, product):
    add_item(api_client, basket, product.barcode, quantity=1)
    response = add_item(api_client, basket, product.barcode, quantity=2)

    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 3
    assert basket.items.count() == 1


def test_product_from_another_store_cannot_be_added(api_client, basket, other_store):
    Product.objects.create(
        store=other_store, barcode="40170725", sku="C1", name="Chocolate", price="40.00"
    )

    response = add_item(api_client, basket, "40170725")

    assert response.status_code == 404


def test_quantity_must_be_positive(api_client, basket, product):
    response = add_item(api_client, basket, product.barcode, quantity=0)

    assert response.status_code == 400


def test_remove_line(api_client, basket, product):
    add_item(api_client, basket, product.barcode)

    response = api_client.delete(f"/api/baskets/{basket.id}/items/{product.barcode}/")

    assert response.status_code == 204
    assert basket.items.count() == 0


def test_remove_line_not_in_basket_is_404(api_client, basket, product):
    response = api_client.delete(f"/api/baskets/{basket.id}/items/{product.barcode}/")

    assert response.status_code == 404


def test_checked_out_basket_cannot_change(api_client, basket, product):
    basket.status = Basket.Status.CHECKED_OUT
    basket.save()

    response = add_item(api_client, basket, product.barcode)

    assert response.status_code == 400
