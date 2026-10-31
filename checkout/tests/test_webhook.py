import json

import pytest

from checkout import services
from checkout.models import Order, PaymentEvent
from checkout.payments import compute_signature

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/payments/webhook/"


@pytest.fixture
def pending_order(filled_basket):
    return Order.objects.create(
        basket=filled_basket,
        store=filled_basket.store,
        total=filled_basket.subtotal(),
        idempotency_key="webhook-test",
    )


def post_webhook(api_client, payload, secret="test-secret", signature=None):
    body = json.dumps(payload).encode("utf-8")
    if signature is None:
        signature = compute_signature(body, secret)
    return api_client.post(
        WEBHOOK_URL, data=body, content_type="application/json", headers={"X-Signature": signature}
    )


@pytest.fixture(autouse=True)
def webhook_secret(settings):
    settings.PAYMENT_WEBHOOK_SECRET = "test-secret"


def succeeded_event(order, event_id="evt_1"):
    return {"event_id": event_id, "type": "payment.succeeded", "order_id": str(order.id)}


def test_bad_signature_is_401(api_client, pending_order):
    response = post_webhook(api_client, succeeded_event(pending_order), secret="wrong-secret")

    assert response.status_code == 401
    assert PaymentEvent.objects.count() == 0


def test_missing_signature_is_401(api_client, pending_order):
    response = post_webhook(api_client, succeeded_event(pending_order), signature="")

    assert response.status_code == 401


def test_succeeded_event_marks_pending_order_paid(api_client, pending_order):
    response = post_webhook(api_client, succeeded_event(pending_order))

    assert response.status_code == 200
    assert response.json() == {"event_id": "evt_1", "duplicate": False}
    pending_order.refresh_from_db()
    assert pending_order.status == Order.Status.PAID
    assert pending_order.paid_at is not None
    assert PaymentEvent.objects.get().order == pending_order


def test_duplicate_event_is_processed_once(api_client, pending_order, monkeypatch):
    # Wrap apply_payment_event so the test can see how many times an event was acted on.
    calls = []
    original_apply = services.apply_payment_event

    def counting_apply(event, order):
        calls.append(event.event_id)
        original_apply(event, order)

    monkeypatch.setattr(services, "apply_payment_event", counting_apply)

    first = post_webhook(api_client, succeeded_event(pending_order))
    second = post_webhook(api_client, succeeded_event(pending_order))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert PaymentEvent.objects.count() == 1
    assert calls == ["evt_1"]


def test_refund_is_recorded_without_changing_the_order(api_client, pending_order):
    pending_order.status = Order.Status.PAID
    pending_order.save()
    payload = {"event_id": "evt_r", "type": "payment.refunded", "order_id": str(pending_order.id)}

    response = post_webhook(api_client, payload)

    assert response.status_code == 200
    assert PaymentEvent.objects.get().type == "payment.refunded"
    pending_order.refresh_from_db()
    assert pending_order.status == Order.Status.PAID


def test_event_for_unknown_order_is_kept_without_an_order(api_client, db):
    payload = {"event_id": "evt_x", "type": "payment.succeeded", "order_id": "not-a-real-id"}

    response = post_webhook(api_client, payload)

    assert response.status_code == 200
    assert PaymentEvent.objects.get().order is None


def test_unsupported_event_type_is_400(api_client, pending_order):
    payload = {"event_id": "evt_2", "type": "payment.disputed", "order_id": str(pending_order.id)}

    response = post_webhook(api_client, payload)

    assert response.status_code == 400
    assert PaymentEvent.objects.count() == 0
