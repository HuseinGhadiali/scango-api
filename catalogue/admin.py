from django.contrib import admin

from .models import Product, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "city", "currency", "created_at"]
    list_filter = ["city", "currency"]
    search_fields = ["code", "name", "city"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "barcode", "sku", "store", "price", "is_active", "updated_at"]
    list_filter = ["store", "is_active"]
    search_fields = ["name", "barcode", "sku"]
