from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from .models import Product, Store
from .serializers import ProductSerializer, StoreSerializer


class ProductPagination(PageNumberPagination):
    # A store can have thousands of products; a phone app only needs one screen at a time.
    page_size = 20


class StoreListView(generics.ListAPIView):
    queryset = Store.objects.order_by("code")
    serializer_class = StoreSerializer


class ProductListView(generics.ListAPIView):
    serializer_class = ProductSerializer
    pagination_class = ProductPagination

    def get_queryset(self):
        # get_object_or_404 makes an unknown store a 404 instead of an empty list.
        store = get_object_or_404(Store, code=self.kwargs["code"])
        products = store.products.filter(is_active=True)

        search = self.request.query_params.get("search", "").strip()
        if search:
            products = products.filter(
                Q(name__icontains=search)
                | Q(sku__icontains=search)
                | Q(barcode__icontains=search)
            )

        # Pagination needs a stable order, otherwise rows can repeat or vanish between pages.
        return products.order_by("name", "barcode")


class ProductDetailView(generics.RetrieveAPIView):
    serializer_class = ProductSerializer

    def get_object(self):
        # One query covers all three 404 cases: unknown store, barcode not in this store,
        # and inactive product.
        return get_object_or_404(
            Product,
            store__code=self.kwargs["code"],
            barcode=self.kwargs["barcode"],
            is_active=True,
        )
