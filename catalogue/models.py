from django.db import models


class Store(models.Model):
    code = models.CharField(max_length=20, unique=True)  # e.g. "PUN-01"
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=50)
    currency = models.CharField(max_length=3, default="INR")  # ISO 4217 code
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Product(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    # A string, not a number: barcodes can start with 0 and are never used in arithmetic.
    barcode = models.CharField(max_length=32)
    sku = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Each store has its own catalogue, so the same barcode may exist in two stores
            # (usually at different prices), but only once within a store.
            models.UniqueConstraint(
                fields=["store", "barcode"], name="unique_barcode_per_store"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.barcode})"
