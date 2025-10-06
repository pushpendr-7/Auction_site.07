from django.contrib import admin
from .models import AuctionItem, Bid, Payment, LedgerBlock


@admin.register(AuctionItem)
class AuctionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "starting_price", "ends_at", "is_active")
    search_fields = ("title", "description", "owner__username")
    list_filter = ("is_active",)


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "bidder", "amount", "created_at")
    search_fields = ("item__title", "bidder__username")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "buyer", "amount", "status", "provider", "created_at")
    list_filter = ("status", "provider")


@admin.register(LedgerBlock)
class LedgerBlockAdmin(admin.ModelAdmin):
    list_display = ("index", "hash", "previous_hash", "timestamp")
