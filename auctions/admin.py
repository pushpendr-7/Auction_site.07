from django.contrib import admin
from .models import AuctionItem, Bid, Payment, LedgerBlock, AuctionParticipant, Order, UserProfile


@admin.register(AuctionItem)
class AuctionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "starting_price", "ends_at", "is_active", "seat_limit", "is_settled")
    search_fields = ("title", "description", "owner__username")
    list_filter = ("is_active",)


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "bidder", "amount", "created_at", "is_active")
    search_fields = ("item__title", "bidder__username")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "buyer", "amount", "purpose", "status", "provider", "created_at")
    list_filter = ("status", "provider", "purpose")


@admin.register(LedgerBlock)
class LedgerBlockAdmin(admin.ModelAdmin):
    list_display = ("index", "hash", "previous_hash", "timestamp")


@admin.register(AuctionParticipant)
class AuctionParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "user", "is_booked", "booking_code", "penalty_due", "last_seen_at")
    search_fields = ("item__title", "user__username", "booking_code")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "buyer", "amount", "status", "created_at", "paid_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "location", "phone_verified_at", "email_verified_at")
