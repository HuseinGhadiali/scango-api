import uuid
from decimal import Decimal

from django.db import models

from catalogue.models import Product, Store


class Basket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open"
        CHECKED_OUT = "checked_out"

    # A UUID, not 1, 2, 3...: the id is handed to the shopper's phone, and a sequential id
    # would let anyone guess other shoppers' baskets.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # PROTECT: baskets and orders are sales history, so deleting a store must not wipe them.
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="baskets")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), Decimal("0.00"))

    def __str__(self):
        return f"Basket {self.id} ({self.status})"


class BasketItem(models.Model):
    basket = models.ForeignKey(Basket, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    # The price when the item was added. Copied, not read from the product, so a price change
    # in the catalogue does not change what the shopper already saw in their basket.
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]  # lines appear in the order they were scanned
        constraints = [
            models.UniqueConstraint(
                fields=["basket", "product"], name="unique_product_per_basket"
            ),
            # PositiveIntegerField still allows 0, and a line with quantity 0 makes no sense.
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="basket_item_quantity_at_least_1"
            ),
        ]

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        PAID = "paid"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    basket = models.OneToOneField(Basket, on_delete=models.PROTECT, related_name="order")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Sent by the client with each checkout request. Unique, so the database itself refuses a
    # second order for the same key even if the application code had a bug.
    idempotency_key = models.CharField(max_length=255, unique=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Order {self.id} ({self.status})"


class PaymentEvent(models.Model):
    """A webhook call from the payment provider, stored exactly as received."""

    class Type(models.TextChoices):
        PAYMENT_SUCCEEDED = "payment.succeeded"
        PAYMENT_REFUNDED = "payment.refunded"

    # The provider's id for the event. Unique, because providers retry webhooks and the same
    # event must only be processed once.
    event_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=50, choices=Type.choices)
    # Null when the event names an order we don't have. The event is still kept, so the
    # reconciliation report can show it instead of it disappearing.
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_events",
    )
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} {self.event_id}"
