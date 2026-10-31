"""Basket and checkout rules, kept out of the views so each rule lives in one place.

Every function that changes a basket locks its row with select_for_update() inside a
transaction. While one request holds the lock, any other request for the same basket waits, so
an item can't be added halfway through a checkout and two checkouts can't run at once.
"""

import uuid

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from catalogue.models import Product

from . import payments
from .models import Basket, BasketItem, Order, PaymentEvent


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

        # Charged while the basket lock is held, so a second request can't start a second
        # charge. The cost is that a slow gateway keeps the lock longer (see the README).
        charge_order(order, payment_token)
        return order, True


def charge_order(order, payment_token):
    gateway = payments.get_payment_gateway()
    result = gateway.charge(
        order.total, order.store.currency, payment_token, order.idempotency_key
    )
    order.payment_reference = result.reference
    if result.succeeded:
        order.status = Order.Status.PAID
        order.paid_at = timezone.now()
    else:
        order.status = Order.Status.FAILED
    order.save(update_fields=["payment_reference", "status", "paid_at"])


def find_order_for_update(order_id):
    """Return the locked order with this id, or None if the id is missing, malformed or unknown."""
    try:
        order_uuid = uuid.UUID(str(order_id))
    except ValueError:
        return None
    return Order.objects.select_for_update().filter(pk=order_uuid).first()


def record_payment_event(event_id, event_type, payload):
    """Store a webhook event and act on it once. Returns (event, created).

    created is False when this event_id was already received; the event is then not
    processed again, because providers resend webhooks they think were not delivered.
    """
    with transaction.atomic():
        order = find_order_for_update(payload.get("order_id"))
        # get_or_create relies on the unique event_id, so even two copies of the same event
        # arriving at the same moment produce one row.
        event, created = PaymentEvent.objects.get_or_create(
            event_id=event_id,
            defaults={"type": event_type, "order": order, "payload": payload},
        )
        if created and order is not None:
            apply_payment_event(event, order)
        return event, created


def apply_payment_event(event, order):
    if event.type == PaymentEvent.Type.PAYMENT_SUCCEEDED:
        # The fake gateway answers at checkout, so the order is usually already paid and this
        # event only confirms it. A pending order is marked paid here; a failed order is left
        # alone and shows up in the reconciliation report instead.
        if order.status == Order.Status.PENDING:
            order.status = Order.Status.PAID
            order.paid_at = timezone.now()
            order.save(update_fields=["status", "paid_at"])
    # payment.refunded: recorded and linked to its order only. There is no "refunded" order
    # status in this version (see the README's open questions).
