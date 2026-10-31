"""Daily reconciliation: do our paid orders and the provider's payment events agree?

For one day and one store it compares:
- paid orders: orders of that store whose paid_at falls on that day, and
- payment events: payment.succeeded events for that store's orders received that day.

An order matches if it has a payment.succeeded event, received on any day, because a webhook
can arrive just after midnight. An event matches if its order is paid. Refund events are not
payment confirmations, so they are left out. Days are UTC days (settings.TIME_ZONE).

The SQL in the comments is what each query means; Django's exact SQL differs a little between
SQLite and PostgreSQL (for example in how DATE() is written).
"""

from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Sum

from catalogue.models import Store

from .models import Order, PaymentEvent

SUCCEEDED = PaymentEvent.Type.PAYMENT_SUCCEEDED


def money(value):
    # A string, because DRF's JSON encoder would turn a bare Decimal into a float. SUM() of no
    # rows is NULL, which becomes None here, so that is reported as 0.00.
    return str((value or Decimal("0")).quantize(Decimal("0.01")))


def paid_orders_on(day):
    return Order.objects.filter(status=Order.Status.PAID, paid_at__date=day)


def succeeded_events_on(day):
    return PaymentEvent.objects.filter(type=SUCCEEDED, received_at__date=day)


def store_report(store, day):
    paid_orders = paid_orders_on(day).filter(store=store)

    # SELECT COUNT(*) AS count, SUM(total) AS total
    # FROM checkout_order
    # WHERE store_id = :store AND status = 'paid' AND DATE(paid_at) = :day;
    order_totals = paid_orders.aggregate(count=Count("id"), total=Sum("total"))

    # SELECT o.id
    # FROM checkout_order o
    # WHERE o.store_id = :store AND o.status = 'paid' AND DATE(o.paid_at) = :day
    #   AND NOT EXISTS (
    #       SELECT 1 FROM checkout_paymentevent e
    #       WHERE e.order_id = o.id AND e.type = 'payment.succeeded'
    #   );
    succeeded_event_for_order = PaymentEvent.objects.filter(order=OuterRef("pk"), type=SUCCEEDED)
    orders_without_event = paid_orders.filter(~Exists(succeeded_event_for_order))

    # SELECT COUNT(*)
    # FROM checkout_paymentevent e
    # JOIN checkout_order o ON o.id = e.order_id
    # WHERE o.store_id = :store AND e.type = 'payment.succeeded' AND DATE(e.received_at) = :day;
    events = succeeded_events_on(day).filter(order__store=store)

    # The same query as above, plus: AND o.status <> 'paid'
    events_without_paid_order = events.exclude(order__status=Order.Status.PAID)

    return {
        "store_code": store.code,
        "paid_orders": {
            "count": order_totals["count"],
            "total": money(order_totals["total"]),
        },
        "payment_events": {"count": events.count()},
        "orders_without_event": [
            str(order_id) for order_id in orders_without_event.values_list("id", flat=True)
        ],
        "events_without_paid_order": list(
            events_without_paid_order.values_list("event_id", flat=True)
        ),
    }


def reconciliation_report(day):
    # One small set of queries per store: simple to read, and fine for a handful of stores.
    stores = Store.objects.order_by("code")

    # Events whose order we don't know can't be put under a store, so they get their own list.
    # SELECT event_id FROM checkout_paymentevent
    # WHERE order_id IS NULL AND type = 'payment.succeeded' AND DATE(received_at) = :day;
    events_without_order = succeeded_events_on(day).filter(order__isnull=True)

    return {
        "date": day.isoformat(),
        "stores": [store_report(store, day) for store in stores],
        "events_without_order": list(events_without_order.values_list("event_id", flat=True)),
    }
