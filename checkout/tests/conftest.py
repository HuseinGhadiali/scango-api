"""Fixtures for the checkout tests (the shared ones are in the project's conftest.py)."""

import pytest

from checkout import payments
from checkout.models import Basket, BasketItem


class CountingGateway(payments.FakeGateway):
    """The fake gateway, but it remembers how many times it was asked to charge."""

    def __init__(self):
        self.charge_count = 0

    def charge(self, amount, currency, payment_token, idempotency_key):
        self.charge_count += 1
        return super().charge(amount, currency, payment_token, idempotency_key)


@pytest.fixture
def gateway(monkeypatch):
    counting_gateway = CountingGateway()
    monkeypatch.setattr(payments, "get_payment_gateway", lambda: counting_gateway)
    return counting_gateway


@pytest.fixture
def basket(store):
    return Basket.objects.create(store=store)


@pytest.fixture
def filled_basket(basket, product):
    BasketItem.objects.create(
        basket=basket, product=product, quantity=2, unit_price=product.price
    )
    return basket
