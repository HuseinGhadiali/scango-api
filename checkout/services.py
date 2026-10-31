"""Basket and checkout rules, kept out of the views so each rule lives in one place.

Every function that changes a basket locks its row with select_for_update() inside a
transaction. While one request holds the lock, any other request for the same basket waits, so
an item can't be added halfway through a checkout and two checkouts can't run at once.
"""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404

from catalogue.models import Product

from .models import Basket, BasketItem, Order


class CheckoutError(Exception):
    """The request can't be done in the basket's current state (answered with 400)."""


class IdempotencyKeyConflict(Exception):
    """The idempotency key was already used for a different basket (answered with 409)."""


def lock_basket(basket_id):
    # Must be called inside transaction.atomic(); the lock is held until the transaction ends.
    return get_object_or_404(Basket.objects.select_for_update(), pk=basket_id)


def lock_open_basket(basket_id):
    basket = lock_basket(basket_id)
    if basket.status != Basket.Status.OPEN:
        raise CheckoutError("Basket is already checked out.")
    return basket


def add_item(basket_id, barcode, quantity):
    with transaction.atomic():
        basket = lock_open_basket(basket_id)
        # Only products from the basket's own store, and only active ones, can be added.
        product = get_object_or_404(
            Product, store=basket.store, barcode=barcode, is_active=True
        )
        item = basket.items.filter(product=product).first()
        if item is None:
            BasketItem.objects.create(
                basket=basket,
                product=product,
                quantity=quantity,
                unit_price=product.price,  # the price snapshot
            )
        else:
            # The line keeps the price from when it was first added.
            item.quantity += quantity
            item.save(update_fields=["quantity"])


def remove_item(basket_id, barcode):
    with transaction.atomic():
        basket = lock_open_basket(basket_id)
        deleted_count, _ = basket.items.filter(product__barcode=barcode).delete()
        if deleted_count == 0:
            raise Http404("This product is not in the basket.")


def checkout_basket(basket_id, idempotency_key, payment_token):
    """Create the order for a basket. Returns (order, created).

    Calling this again with the same key and basket returns the first order with
    created=False, so a client that retries after a timeout is never charged twice.
    """
    with transaction.atomic():
        basket = lock_basket(basket_id)

        # Checked after taking the lock: if two identical requests arrive together, the second
        # waits for the first to finish and then finds its order here.
        existing_order = Order.objects.filter(idempotency_key=idempotency_key).first()
        if existing_order is not None:
            if existing_order.basket_id != basket.id:
                raise IdempotencyKeyConflict(
                    "This Idempotency-Key was already used for a different basket."
                )
            return existing_order, False

        if basket.status != Basket.Status.OPEN:
            raise CheckoutError("Basket is already checked out.")
        if not basket.items.exists():
            raise CheckoutError("Basket is empty.")

        order = Order.objects.create(
            basket=basket,
            store=basket.store,
            total=basket.subtotal(),
            idempotency_key=idempotency_key,
        )
        # The basket is closed as soon as it becomes an order, so its items can't change.
        basket.status = Basket.Status.CHECKED_OUT
        basket.save(update_fields=["status"])
        return order, True
