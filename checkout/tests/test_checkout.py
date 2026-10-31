import pytest

from checkout.models import Basket, BasketItem, Order

pytestmark = pytest.mark.django_db


def checkout(api_client, basket, key="key-1", token="tok_success"):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return api_client.post(
        f"/api/baskets/{basket.id}/checkout/",
        {"payment_token": token},
        format="json",
        headers=headers,
    )


def test_missing_idempotency_key_is_400(api_client, filled_basket, gateway):
    response = checkout(api_client, filled_basket, key=None)

    assert response.status_code == 400
    assert Order.objects.count() == 0
    assert gateway.charge_count == 0


def test_successful_checkout(api_client, filled_basket, gateway):
    response = checkout(api_client, filled_basket)

    assert response.status_code == 201
    order = Order.objects.get()
    assert order.status == Order.Status.PAID
    assert str(order.total) == "550.00"  # 2 x 275.00
    assert order.paid_at is not None
    assert order.payment_reference.startswith("fake_")
    filled_basket.refresh_from_db()
    assert filled_basket.status == Basket.Status.CHECKED_OUT


def test_same_key_twice_gives_one_order_and_one_charge(api_client, filled_basket, gateway):
    first = checkout(api_client, filled_basket, key="retry-key")
    second = checkout(api_client, filled_basket, key="retry-key")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert Order.objects.count() == 1
    assert gateway.charge_count == 1


def test_same_key_on_another_basket_is_409(api_client, filled_basket, store, product, gateway):
    other_basket = Basket.objects.create(store=store)
    BasketItem.objects.create(
        basket=other_basket, product=product, quantity=1, unit_price=product.price
    )
    checkout(api_client, filled_basket, key="shared-key")

    response = checkout(api_client, other_basket, key="shared-key")

    assert response.status_code == 409
    assert Order.objects.count() == 1
    assert gateway.charge_count == 1


def test_failed_payment_marks_order_failed(api_client, filled_basket, gateway):
    response = checkout(api_client, filled_basket, token="tok_fail")

    assert response.json()["status"] == "failed"
    order = Order.objects.get()
    assert order.status == Order.Status.FAILED
    assert order.paid_at is None


def test_empty_basket_is_400(api_client, basket, gateway):
    response = checkout(api_client, basket)

    assert response.status_code == 400
    assert gateway.charge_count == 0


def test_checked_out_basket_with_a_new_key_is_400(api_client, filled_basket, gateway):
    checkout(api_client, filled_basket, key="first-key")

    response = checkout(api_client, filled_basket, key="second-key")

    assert response.status_code == 400
    assert gateway.charge_count == 1


def test_get_order(api_client, filled_basket, gateway):
    order_id = checkout(api_client, filled_basket).json()["id"]

    response = api_client.get(f"/api/orders/{order_id}/")

    assert response.status_code == 200
    assert response.json()["total"] == "550.00"
    assert response.json()["store_code"] == "PUN-01"
