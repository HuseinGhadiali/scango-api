"""The payment gateway interface, a fake implementation, and webhook signature checks.

Checkout only talks to PaymentGateway, so a real provider could be added later as another
subclass without changing the checkout code. There is no real provider and no card data
anywhere: the client sends an opaque token, as it would after a provider's own SDK has taken
the card details.
"""

import hashlib
import hmac
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings

SUCCEEDED = "succeeded"
FAILED = "failed"


@dataclass(frozen=True)
class PaymentResult:
    status: str  # SUCCEEDED or FAILED
    reference: str  # the gateway's id for this payment, kept on the order

    @property
    def succeeded(self):
        return self.status == SUCCEEDED


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, amount, currency, payment_token, idempotency_key):
        """Charge amount (a Decimal) and return a PaymentResult."""


class FakeGateway(PaymentGateway):
    """Decides the result from the token alone, so demos and tests are predictable."""

    def charge(self, amount, currency, payment_token, idempotency_key):
        # Real gateways also accept an idempotency key; a real implementation would pass ours
        # on, so even a retried call to the gateway could not charge twice.
        reference = f"fake_{uuid.uuid4().hex[:16]}"
        if payment_token == "tok_success":
            return PaymentResult(status=SUCCEEDED, reference=reference)
        # "tok_fail", and any token the gateway doesn't recognise, is declined.
        return PaymentResult(status=FAILED, reference=reference)


def get_payment_gateway():
    # The one place that chooses the gateway; tests replace this function to count charges.
    return FakeGateway()


def compute_signature(body, secret):
    """HMAC-SHA256 of the raw request body, as a hex string."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_is_valid(body, signature):
    expected = compute_signature(body, settings.PAYMENT_WEBHOOK_SECRET)
    # compare_digest takes the same time however many characters match, so an attacker can't
    # work out the signature one character at a time from response times. Both sides are
    # bytes because compare_digest rejects non-ASCII strings.
    return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))
