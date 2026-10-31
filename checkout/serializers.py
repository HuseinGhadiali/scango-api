from rest_framework import serializers

from .models import Basket, BasketItem, Order


class BasketItemSerializer(serializers.ModelSerializer):
    barcode = serializers.CharField(source="product.barcode")
    name = serializers.CharField(source="product.name")
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        model = BasketItem
        fields = ["barcode", "name", "quantity", "unit_price", "line_total"]


class BasketSerializer(serializers.ModelSerializer):
    store_code = serializers.CharField(source="store.code")
    items = BasketItemSerializer(many=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        model = Basket
        fields = ["id", "store_code", "status", "items", "subtotal", "created_at"]


class OrderSerializer(serializers.ModelSerializer):
    store_code = serializers.CharField(source="store.code")

    class Meta:
        model = Order
        fields = [
            "id",
            "basket",
            "store_code",
            "total",
            "status",
            "payment_reference",
            "created_at",
            "paid_at",
        ]


# Request bodies


class CreateBasketSerializer(serializers.Serializer):
    store_code = serializers.CharField()


class AddItemSerializer(serializers.Serializer):
    barcode = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)


class CheckoutSerializer(serializers.Serializer):
    payment_token = serializers.CharField()
