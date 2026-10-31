from datetime import datetime, timezone
from decimal import Decimal

import pytest

from checkout.models import Basket, Order, PaymentEvent

pytestmark = pytest.mark.django_db

REPORT_URL = "/api/reports/reconciliation/"
DAY = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
NEXT_DAY = datetime(2026, 10, 31, 0, 5, tzinfo=timezone.utc)


def make_order(store, total, status=Order.Status.PAID, paid_at=DAY):
    basket = Basket.objects.create(store=store, status=Basket.Status.CHECKED_OUT)
    return Order.objects.create(
        basket=basket,
        store=store,
        total=Decimal(total),
        status=status,
        idempotency_key=f"key-{basket.id}",
        paid_at=paid_at if status == Order.Status.PAID else None,
    )


def make_event(event_id, order, received_at=DAY, event_type="payment.succeeded"):
    event = PaymentEvent.objects.create(
        event_id=event_id, type=event_type, order=order, payload={"event_id": event_id}
    )
    # received_at is auto_now_add, so it can only be changed after the row exists.
    PaymentEvent.objects.filter(pk=event.pk).update(received_at=received_at)
    return event


def get_report(api_client, date="2026-10-30"):
    return api_client.get(REPORT_URL, {"date": date})


def store_section(report, store_code):
    return next(s for s in report["stores"] if s["store_code"] == store_code)


def test_matching_orders_and_events(api_client, store, other_store):
    first = make_order(store, "100.00")
    second = make_order(store, "50.50")
    make_event("evt_1", first)
    make_event("evt_2", second)

    response = get_report(api_client)

    assert response.status_code == 200
    pune = store_section(response.json(), "PUN-01")
    assert pune == {
        "store_code": "PUN-01",
        "paid_orders": {"count": 2, "total": "150.50"},
        "payment_events": {"count": 2},
        "orders_without_event": [],
        "events_without_paid_order": [],
    }
    assert store_section(response.json(), "MUM-01")["paid_orders"] == {"count": 0, "total": "0.00"}


def test_paid_order_without_event_is_listed(api_client, store):
    order = make_order(store, "100.00")

    pune = store_section(get_report(api_client).json(), "PUN-01")

    assert pune["orders_without_event"] == [str(order.id)]


def test_event_without_paid_order_is_listed(api_client, store):
    failed_order = make_order(store, "100.00", status=Order.Status.FAILED)
    make_event("evt_failed", failed_order)

    pune = store_section(get_report(api_client).json(), "PUN-01")

    assert pune["paid_orders"]["count"] == 0
    assert pune["payment_events"]["count"] == 1
    assert pune["events_without_paid_order"] == ["evt_failed"]


def test_event_for_unknown_order_is_listed_separately(api_client, store):
    make_event("evt_orphan", None)

    report = get_report(api_client).json()

    assert report["events_without_order"] == ["evt_orphan"]


def test_event_arriving_after_midnight_still_matches(api_client, store):
    order = make_order(store, "100.00")
    make_event("evt_late", order, received_at=NEXT_DAY)

    pune = store_section(get_report(api_client).json(), "PUN-01")

    assert pune["orders_without_event"] == []
    assert pune["payment_events"]["count"] == 0  # the event belongs to the next day's count


def test_other_days_and_refunds_are_ignored(api_client, store):
    make_order(store, "100.00", paid_at=NEXT_DAY)
    refunded = make_order(store, "20.00")
    make_event("evt_paid", refunded)
    make_event("evt_refund", refunded, event_type="payment.refunded")

    pune = store_section(get_report(api_client).json(), "PUN-01")

    assert pune["paid_orders"] == {"count": 1, "total": "20.00"}
    assert pune["payment_events"]["count"] == 1


@pytest.mark.parametrize("date", ["", "30-10-2026", "2026-13-01"])
def test_bad_or_missing_date_is_400(api_client, db, date):
    assert get_report(api_client, date).status_code == 400


def test_report_is_read_only(api_client, db):
    assert api_client.post(REPORT_URL, {}, format="json").status_code == 405
