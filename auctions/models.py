from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
import uuid

User = get_user_model()


class AuctionItem(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_items')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='items/')
    address = models.CharField(max_length=255, help_text='Pickup/Shipping address')
    starting_price = models.DecimalField(max_digits=12, decimal_places=2)
    buy_now_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    seat_limit = models.PositiveIntegerField(default=0, help_text='Max seats available to bid')
    is_settled = models.BooleanField(default=False)
    # When the seller starts a live video call for this item
    call_started_at = models.DateTimeField(null=True, blank=True)
    # Optional Google Meet link for the live call
    meet_url = models.URLField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.title} (#{self.pk})"

    @property
    def highest_bid(self):
        return self.bids.filter(is_active=True).order_by('-amount', 'created_at').first()

    def can_accept_bids(self) -> bool:
        now = timezone.now()
        if not (self.is_active and self.starts_at <= now < self.ends_at):
            return False
        # Market open between 06:00 and 01:00 (next day) local time
        local_now = timezone.localtime(now)
        return local_now.hour >= 6 or local_now.hour < 1

    @property
    def participants_count(self) -> int:
        return self.participants.filter(is_booked=True, unbooked_at__isnull=True).count()


class Bid(models.Model):
    item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bids')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    tx_id = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Bid {self.amount} on {self.item_id} by {self.bidder_id}"


class AuctionParticipant(models.Model):
    item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_participations')
    joined_at = models.DateTimeField(auto_now_add=True)
    is_booked = models.BooleanField(default=False)
    booking_code = models.CharField(max_length=12, blank=True)
    code_verified_at = models.DateTimeField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    preview_started_at = models.DateTimeField(null=True, blank=True)
    unbooked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    penalty_due = models.BooleanField(default=False)

    class Meta:
        unique_together = ('item', 'user')

    def __str__(self) -> str:
        return f"Participant {self.user_id} in item {self.item_id}"


class Payment(models.Model):
    item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    # The intended recipient of this payment (e.g., seller for orders). Null implies platform.
    recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_received')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.CharField(max_length=20, default='order')  # order, seat, penalty, buy_now
    provider = models.CharField(max_length=50, default='google_pay')
    provider_ref = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=30, default='pending')
    transaction_id = models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False)
    # Snapshot of recipient bank/UPI details at the time of payment (for offline/bank flows)
    recipient_upi_vpa = models.CharField(max_length=120, blank=True, default='')
    recipient_bank_holder_name = models.CharField(max_length=120, blank=True, default='')
    recipient_bank_account_number = models.CharField(max_length=34, blank=True, default='')
    recipient_bank_ifsc = models.CharField(max_length=20, blank=True, default='')
    # Blockchain fields
    chain = models.CharField(max_length=30, blank=True)  # polygon, ethereum, etc.
    token_symbol = models.CharField(max_length=20, blank=True)  # MATIC, ETH, USDT
    onchain_amount_wei = models.CharField(max_length=80, blank=True)  # store as string
    recipient_address = models.CharField(max_length=80, blank=True)
    payer_address = models.CharField(max_length=80, blank=True)
    tx_hash = models.CharField(max_length=100, blank=True)
    confirmations = models.PositiveIntegerField(default=0)
    onchain_status = models.CharField(max_length=30, blank=True)  # pending, confirmed, failed
    created_at = models.DateTimeField(auto_now_add=True)
    # Indicates that post-payment effects (wallet credit, seat activation, etc.) were applied
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Payment {self.amount} for {self.item_id} ({self.status})"


class Order(models.Model):
    item = models.ForeignKey(AuctionItem, on_delete=models.CASCADE, related_name='orders')
    buyer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='created')  # created, paid, delivered, cancelled
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Order {self.pk} for item {self.item_id} ({self.status})"


class LedgerBlock(models.Model):
    index = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    previous_hash = models.CharField(max_length=64)
    data = models.JSONField()
    nonce = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ['index']

    def __str__(self) -> str:
        return f"Block {self.index} {self.hash[:8]}"

# Create your models here.


class UserProfile(models.Model):
    """Additional user information and verification state."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True)
    location = models.CharField(max_length=120, blank=True, help_text='City/Area')
    phone_otp_code = models.CharField(max_length=6, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verify_token = models.CharField(max_length=64, blank=True)
    # Payment method details (optional; used for Google Pay/Bank flows)
    upi_vpa = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text='Your UPI ID (e.g., name@bank)'
    )
    bank_holder_name = models.CharField(max_length=120, blank=True, default='')
    bank_account_number = models.CharField(max_length=34, blank=True, default='')
    bank_ifsc = models.CharField(max_length=20, blank=True, default='')
    # Explicit consent to auto-debit linked bank for settlements
    auto_debit_consent = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Profile for {self.user_id}"


class Wallet(models.Model):
    """Simple user wallet with INR balance.
    Funds are added via payments (Google Pay/Bank/Crypto) and deducted on settlement.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Wallet({self.user_id}) ₹{self.balance}"


class WalletTransaction(models.Model):
    KIND_CHOICES = (
        ('credit', 'Credit'),
        ('debit', 'Debit'),
        ('hold_reserve', 'Hold Reserve'),
        ('hold_release', 'Hold Release'),
        ('hold_consume', 'Hold Consume'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet_transactions')
    item = models.ForeignKey('AuctionItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='wallet_transactions')
    payment = models.ForeignKey('Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='wallet_transactions')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.kind} ₹{self.amount} (user {self.user_id})"


class WalletHold(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('released', 'Released'),
        ('consumed', 'Consumed'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet_holds')
    item = models.ForeignKey('AuctionItem', on_delete=models.CASCADE, related_name='wallet_holds')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Only one active hold per user+item to avoid double reservation
            models.UniqueConstraint(
                fields=['user', 'item'],
                condition=models.Q(status='active'),
                name='unique_active_hold_per_user_item',
            )
        ]

    def __str__(self) -> str:
        return f"Hold ₹{self.amount} on item {self.item_id} ({self.status})"
