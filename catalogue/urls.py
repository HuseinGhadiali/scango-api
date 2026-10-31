from django.urls import path

from . import views

urlpatterns = [
    path("stores/", views.StoreListView.as_view(), name="store-list"),
    path(
        "stores/<str:code>/products/",
        views.ProductListView.as_view(),
        name="product-list",
    ),
    path(
        "stores/<str:code>/products/<str:barcode>/",
        views.ProductDetailView.as_view(),
        name="product-detail",
    ),
]
