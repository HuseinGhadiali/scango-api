from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalogue.models import Store

from . import services
from .models import Basket, Order
from .serializers import (
    AddItemSerializer,
    BasketSerializer,
    CheckoutSerializer,
    CreateBasketSerializer,
    OrderSerializer,
)

# Matches Order.idempotency_key, so a longer key is a clear 400 rather than a database error.
MAX_IDEMPOTENCY_KEY_LENGTH = 255


def basket_response(basket_id, response_status=status.HTTP_200_OK):
    # Fetch the basket with its items and products in two extra queries rather than one per line.
    basket = Basket.objects.select_related("store").prefetch_related("items__product").get(
        pk=basket_id
    )
    return Response(BasketSerializer(basket).data, status=response_status)


class BasketCreateView(APIView):
    def post(self, request):
        serializer = CreateBasketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        store = Store.objects.filter(code=serializer.validated_data["store_code"]).first()
        if store is None:
            return Response(
                {"store_code": ["Unknown store."]}, status=status.HTTP_400_BAD_REQUEST
            )

        basket = Basket.objects.create(store=store)
        return basket_response(basket.id, status.HTTP_201_CREATED)


class BasketDetailView(generics.RetrieveAPIView):
    queryset = Basket.objects.select_related("store").prefetch_related("items__product")
    serializer_class = BasketSerializer
    lookup_url_kwarg = "basket_id"


class BasketItemsView(APIView):
    def post(self, request, basket_id):
        serializer = AddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.add_item(
                basket_id,
                serializer.validated_data["barcode"],
                serializer.validated_data["quantity"],
            )
        except services.CheckoutError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        # The whole basket is returned so the app can redraw it from one response.
        return basket_response(basket_id)


class BasketItemDetailView(APIView):
    def delete(self, request, basket_id, barcode):
        try:
            services.remove_item(basket_id, barcode)
        except services.CheckoutError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CheckoutView(APIView):
    def post(self, request, basket_id):
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return Response(
                {"detail": "The Idempotency-Key header is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            return Response(
                {"detail": "The Idempotency-Key header is too long (max 255 characters)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order, created = services.checkout_basket(
                basket_id, idempotency_key, serializer.validated_data["payment_token"]
            )
        except services.IdempotencyKeyConflict as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        except services.CheckoutError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        # 201 the first time; 200 for a retry, which gets back the order it already created.
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(OrderSerializer(order).data, status=response_status)


class OrderDetailView(generics.RetrieveAPIView):
    queryset = Order.objects.select_related("store")
    serializer_class = OrderSerializer
    lookup_url_kwarg = "order_id"
