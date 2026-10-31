from django.urls import path

from . import views

urlpatterns = [
    path("baskets/", views.BasketCreateView.as_view(), name="basket-create"),
    path("baskets/<uuid:basket_id>/", views.BasketDetailView.as_view(), name="basket-detail"),
    path(
        "baskets/<uuid:basket_id>/items/",
        views.BasketItemsView.as_view(),
        name="basket-items",
    ),
    path(
        "baskets/<uuid:basket_id>/items/<str:barcode>/",
        views.BasketItemDetailView.as_view(),
        name="basket-item-detail",
    ),
    path(
        "baskets/<uuid:basket_id>/checkout/",
        views.CheckoutView.as_view(),
        name="basket-checkout",
    ),
    path("orders/<uuid:order_id>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("payments/webhook/", views.PaymentWebhookView.as_view(), name="payment-webhook"),
]
