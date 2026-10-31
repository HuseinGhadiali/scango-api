from rest_framework import serializers

from .models import Product, Store


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["code", "name", "city", "currency"]


class ProductSerializer(serializers.ModelSerializer):
    # DRF renders DecimalField as a string ("1299.00") by default, which keeps money exact in
    # JSON instead of turning it into a float.
    class Meta:
        model = Product
        fields = ["barcode", "sku", "name", "price"]
