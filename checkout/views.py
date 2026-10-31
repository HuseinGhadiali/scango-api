import json
from datetime import datetime

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalogue.models import Store

from . import payments, services
from .reconciliation import reconciliation_report
from .models import Basket, Order, PaymentEvent
from .serializers import (
    AddItemSerializer,
    BasketSerializer,
    CheckoutSerializer,
    CreateBasketSerializer,
    OrderSerializer,
)

# Matches Order.idempotency_key, so a longer key is a clear 400 rather than a database error.
MAX_IDEMPOTENCY_KEY_LENGTH = 255


def bad_request(message):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


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
            return bad_request(str(error))
        # The whole basket is returned so the app can redraw it from one response.
        return basket_response(basket_id)


class BasketItemDetailView(APIView):
    def delete(self, request, basket_id, barcode):
        try:
            services.remove_item(basket_id, barcode)
        except services.CheckoutError as error:
            return bad_request(str(error))
        return Response(status=status.HTTP_204_NO_CONTENT)


class CheckoutView(APIView):
    def post(self, request, basket_id):
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return bad_request("The Idempotency-Key header is required.")
        if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            return bad_request("The Idempotency-Key header is too long (max 255 characters).")

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order, created = services.checkout_basket(
                basket_id, idempotency_key, serializer.validated_data["payment_token"]
            )
        except services.IdempotencyKeyConflict as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        except services.CheckoutError as error:
            return bad_request(str(error))

        # 201 the first time; 200 for a retry, which gets back the order it already created.
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(OrderSerializer(order).data, status=response_status)


class OrderDetailView(generics.RetrieveAPIView):
    queryset = Order.objects.select_related("store")
    serializer_class = OrderSerializer
    lookup_url_kwarg = "order_id"


class PaymentWebhookView(APIView):
    # The caller is the payment provider's server, not a logged-in user, so the signature is
    # the only authentication. With no authentication classes DRF also skips the CSRF check,
    # which only protects browsers.
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        # The signature covers the exact bytes sent, so it is checked on the raw body before
        # anything parses it. Parsing and re-serialising could change spacing or key order.
        raw_body = request.body
        signature = request.headers.get("X-Signature", "")
        if not payments.signature_is_valid(raw_body, signature):
            return Response(
                {"detail": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            payload = json.loads(raw_body)
        except ValueError:
            return bad_request("Body is not valid JSON.")
        if not isinstance(payload, dict):
            return bad_request("Body must be a JSON object.")

        event_id = payload.get("event_id")
        event_type = payload.get("type")
        if not isinstance(event_id, str) or not event_id:
            return bad_request("event_id is required.")
        if event_type not in PaymentEvent.Type.values:
            return bad_request(f"Unsupported event type {event_type!r}.")

        _, created = services.record_payment_event(event_id, event_type, payload)
        # A repeated event also gets 200: it tells the provider "received", so it stops retrying.
        return Response({"event_id": event_id, "duplicate": not created})


class ReconciliationReportView(APIView):
    # Only get() is defined, so DRF answers any other method with 405: the report is read-only.
    def get(self, request):
        raw_date = request.query_params.get("date", "")
        try:
            day = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            return bad_request("The date parameter is required, as YYYY-MM-DD.")
        return Response(reconciliation_report(day))
