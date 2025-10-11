from decimal import Decimal, InvalidOperation
import random
import string
import secrets
import json
import zipfile
import io
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import HttpRequest, HttpResponse, JsonResponse
from django import forms
from django.db import transaction
from django.views.decorators.http import require_GET, require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.views.decorators.csrf import csrf_exempt

from .models import (
    AuctionItem,
    Bid,
    Payment,
    AuctionParticipant,
    Order,
    UserProfile,
    Wallet,
    WalletTransaction,
    WalletHold,
    Transaction,
)
from urllib.parse import urlparse
from .utils import append_ledger_block, get_available_balance, get_or_create_wallet, apply_payment_effects
from django.conf import settings
from .blockchain import inr_to_token_quote, validate_native_transfer
from .forms import BankLinkForm
from .models import BankAccount


class AuctionItemForm(forms.ModelForm):
    class Meta:
        model = AuctionItem
        fields = [
            'title',
            'description',
            'image',
            'address',
            'starting_price',
            'buy_now_price',
            'starts_at',
            'ends_at',
            'seat_limit',
        ]
    
    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get('starts_at')
        ends_at = cleaned_data.get('ends_at')
        starting_price = cleaned_data.get('starting_price')
        buy_now_price = cleaned_data.get('buy_now_price')
        
        if starts_at and ends_at:
            if ends_at <= starts_at:
                raise forms.ValidationError('End time must be after start time.')
            if ends_at <= timezone.now():
                raise forms.ValidationError('End time must be in the future.')
        
        if starting_price and starting_price <= 0:
            raise forms.ValidationError('Starting price must be positive.')
        
        if buy_now_price and starting_price:
            if buy_now_price <= starting_price:
                raise forms.ValidationError('Buy now price must be higher than starting price.')
        
        return cleaned_data


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    phone = forms.CharField(required=True, max_length=20)
    location = forms.CharField(required=True, max_length=120)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        # Ensure profile exists and populate
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data["phone"]
        profile.location = self.cleaned_data["location"]
        # Generate OTP and email token
        profile.phone_otp_code = ''.join(random.choices(string.digits, k=6))
        profile.email_verify_token = secrets.token_hex(16)
        profile.save()
        return user


def home(request: HttpRequest) -> HttpResponse:
    # Show all items on the home page
    items = AuctionItem.objects.all().order_by('-ends_at')
    return render(request, 'auctions/home.html', {'items': items})


def register_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Authenticate before login so the auth backend is set
            raw_password = form.cleaned_data.get('password1')
            authenticated_user = authenticate(request, username=user.username, password=raw_password)
            if authenticated_user is not None:
                login(request, authenticated_user)
                messages.success(request, 'Account created. Verify your phone and email.')
                return redirect('verify')
            # If authentication fails (unlikely), ask the user to log in manually
            messages.success(request, 'Account created. Please log in to continue verification.')
            return redirect('login')
    else:
        form = RegistrationForm()
    return render(request, 'auctions/register.html', {'form': form})


def login_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
    else:
        form = AuthenticationForm(request)
    return render(request, 'auctions/login.html', {'form': form})


def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect('home')


@login_required
def item_create(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = AuctionItemForm(request.POST, request.FILES)
        if form.is_valid():
            item: AuctionItem = form.save(commit=False)
            item.owner = request.user
            item.save()
            AuctionParticipant.objects.get_or_create(item=item, user=request.user)
            messages.success(request, 'Item listed for auction!')
            return redirect('item_detail', pk=item.pk)
    else:
        form = AuctionItemForm()
    return render(request, 'auctions/item_form.html', {'form': form})


def item_detail(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    # Show recent bids including inactive ones for transparency
    bids = item.bids.select_related('bidder').order_by('-created_at')[:50]
    participant = None
    if request.user.is_authenticated:
        participant = AuctionParticipant.objects.filter(item=item, user=request.user).first()
    # Whether this user has verified their join code for this item (persisted)
    has_verified_code = False
    if request.user.is_authenticated:
        ap = AuctionParticipant.objects.filter(item=item, user=request.user).only('code_verified_at').first()
        has_verified_code = bool(ap and ap.code_verified_at)
    owner_bank_accounts = None
    if request.user.is_authenticated and request.user.id == item.owner_id:
        # Owner-only visibility
        try:
            owner_bank_accounts = item.owner.bank_accounts.all()
        except Exception:
            owner_bank_accounts = None
    return render(request, 'auctions/item_detail.html', {
        'item': item,
        'bids': bids,
        'participant': participant,
        'has_verified_code': has_verified_code,
        'owner_bank_accounts': owner_bank_accounts,
    })


@login_required
def place_bid(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id == request.user.id:
        messages.error(request, 'Owners cannot bid on their own items.')
        return redirect('item_detail', pk=pk)
    if not item.can_accept_bids():
        messages.error(request, 'Bidding is closed for this item.')
        return redirect('item_detail', pk=pk)

    # Ensure the user has a booked seat
    participant, _ = AuctionParticipant.objects.get_or_create(item=item, user=request.user)
    if not participant.is_booked:
        messages.error(request, 'Only seat-booked users can bid. Book a seat first (₹5).')
        return redirect('item_detail', pk=pk)

    if participant.penalty_due:
        messages.error(request, 'Penalty due ₹200. Please pay the penalty to continue.')
        return redirect('item_detail', pk=pk)

    if item.participants.count() < 2:
        messages.error(request, 'At least 2 participants are required to start bidding.')
        return redirect('item_detail', pk=pk)

    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, 'Invalid bid amount.')
        return redirect('item_detail', pk=pk)

    min_allowed = item.starting_price
    if item.highest_bid:
        min_allowed = max(min_allowed, item.highest_bid.amount + Decimal('1.00'))

    if amount < min_allowed:
        messages.error(request, f'Bid must be at least ₹{min_allowed}.')
        return redirect('item_detail', pk=pk)
    
    # Additional validation: bid should not be unreasonably high
    max_reasonable_bid = item.starting_price * Decimal('1000')  # 1000x starting price
    if amount > max_reasonable_bid:
        messages.error(request, f'Bid amount seems unreasonably high. Maximum allowed is ₹{max_reasonable_bid}.')
        return redirect('item_detail', pk=pk)

    # Wallet balance check and hold logic
    existing_hold = WalletHold.objects.filter(item=item, user=request.user, status='active').first()
    required_extra = amount - (existing_hold.amount if existing_hold else Decimal('0'))
    if required_extra < 0:
        required_extra = Decimal('0')
    available = get_available_balance(request.user)
    if available < required_extra:
        messages.error(request, f'Insufficient wallet balance. Need ₹{required_extra} more. Recharge your wallet.')
        return redirect('wallet')

    with transaction.atomic():
        # Re-evaluate highest and min_allowed within transaction for correctness
        item_refreshed = AuctionItem.objects.select_for_update().get(pk=item.pk)
        current_highest = item_refreshed.bids.filter(is_active=True).order_by('-amount', 'created_at').first()
        new_min_allowed = item_refreshed.starting_price
        if current_highest:
            new_min_allowed = max(new_min_allowed, current_highest.amount + Decimal('1.00'))
        if amount < new_min_allowed:
            messages.error(request, f'Bid must be at least {new_min_allowed}.')
            return redirect('item_detail', pk=pk)

        # Lock wallet and re-check available balance under lock
        wallet = get_or_create_wallet(request.user)
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        hold = WalletHold.objects.select_for_update().filter(item=item_refreshed, user=request.user, status='active').first()
        # Determine additional funds needed
        if hold:
            delta = amount - hold.amount
        else:
            delta = amount
        if delta < 0:
            delta = Decimal('0')
        # Check available now (excludes all active holds)
        available_now = get_available_balance(request.user)
        if available_now < delta:
            messages.error(request, f'Insufficient wallet balance. Need ₹{delta} more. Recharge your wallet.')
            return redirect('wallet')
        # Reserve/adjust hold for this user
        if hold:
            if delta > 0:
                hold.amount = amount
                hold.save(update_fields=['amount', 'updated_at'])
                WalletTransaction.objects.create(
                    user=request.user,
                    item=item_refreshed,
                    kind='hold_reserve',
                    amount=delta,
                    balance_after=wallet.balance,
                )
        else:
            hold = WalletHold.objects.create(user=request.user, item=item_refreshed, amount=amount, status='active')
            WalletTransaction.objects.create(
                user=request.user,
                item=item_refreshed,
                kind='hold_reserve',
                amount=amount,
                balance_after=wallet.balance,
            )

        # Release previous highest bidder's hold if any
        if current_highest and current_highest.bidder_id != request.user.id:
            prev_hold = WalletHold.objects.select_for_update().filter(item=item_refreshed, user=current_highest.bidder, status='active').first()
            if prev_hold:
                prev_hold.status = 'released'
                prev_hold.save(update_fields=['status', 'updated_at'])
                prev_wallet = get_or_create_wallet(current_highest.bidder)
                WalletTransaction.objects.create(
                    user=current_highest.bidder,
                    item=item_refreshed,
                    kind='hold_release',
                    amount=prev_hold.amount,
                    balance_after=prev_wallet.balance,
                )

        new_bid = Bid.objects.create(item=item_refreshed, bidder=request.user, amount=amount, is_active=True)
        # Transaction log for audit (informational)
        Transaction.objects.create(
            user=request.user,
            item=item_refreshed,
            tx_type='BID',
            status='INFO',
            amount=amount,
            metadata={'bid_tx_id': str(new_bid.tx_id)},
        )
        append_ledger_block({
            'type': 'bid_placed',
            'item_id': item_refreshed.pk,
            'user_id': request.user.pk,
            'amount': str(amount),
            'bid_tx_id': new_bid.tx_id,
            'timestamp': timezone.now().isoformat(),
        })

    # Broadcast new bid via Channels (best-effort, non-blocking)
    try:
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"auction_{item.pk}",
                {
                    'type': 'new_bid',
                    'bid': {
                        'bidder__username': request.user.username,
                        'amount': str(amount),
                        'created_at': timezone.now().isoformat(),
                        'is_active': True,
                    },
                }
            )
    except Exception:
        # Ignore broadcast errors
        pass

    messages.success(request, 'Bid placed! Funds reserved until you are outbid or auction ends.')
    return redirect('item_detail', pk=pk)


@login_required
def buy_now(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.buy_now_price is None:
        messages.error(request, 'Buy now is not available for this item.')
        return redirect('item_detail', pk=pk)
    # Provider selection via query (?provider=bank|gpay|crypto|wallet)
    provider_param = (request.GET.get('provider') or 'gpay').lower()
    provider = 'google_pay'
    if provider_param in ('bank', 'upi', 'neft', 'imps'):
        provider = 'bank'
    elif provider_param in ('crypto', 'blockchain'):
        provider = 'blockchain'
    payment = Payment.objects.create(
        item=item,
        buyer=request.user,
        amount=item.buy_now_price,
        purpose='buy_now',
        provider=provider,
        status='pending',
    )
    if provider == 'blockchain':
        return redirect('crypto_pay_start', pk=payment.pk)
    elif provider == 'bank':
        return redirect('bank_pay_start', pk=payment.pk)
    return redirect('google_pay_start', pk=payment.pk)


@login_required
def google_pay_start(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    # Placeholder: In a real integration, generate payment token/session here.
    payment.provider_ref = f"SIM-{payment.pk}-{timezone.now().timestamp()}"
    payment.status = 'processing'
    payment.save()
    # Simulate redirect to Google Pay and immediate callback
    return redirect('google_pay_callback', pk=payment.pk)


@login_required
def bank_pay_start(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    # Determine recipient: platform for recharge/seat/penalty; seller for order/buy_now
    recipient_user = None
    if payment.purpose in ('order', 'buy_now') and payment.item:
        recipient_user = payment.item.owner
    # Snapshot recipient details: prefer seller's profile; fallback to platform settings
    from django.conf import settings
    rec_upi = ''
    rec_holder = ''
    rec_acc = ''
    rec_ifsc = ''
    if recipient_user:
        rec_profile, _ = UserProfile.objects.get_or_create(user=recipient_user)
        rec_upi = rec_profile.upi_vpa or ''
        rec_holder = rec_profile.bank_holder_name or ''
        rec_acc = rec_profile.bank_account_number or ''
        rec_ifsc = rec_profile.bank_ifsc or ''
    # Platform fallback for all cases
    rec_upi = rec_upi or getattr(settings, 'PLATFORM_UPI_VPA', '')
    rec_holder = rec_holder or getattr(settings, 'PLATFORM_BANK_HOLDER_NAME', '')
    rec_acc = rec_acc or getattr(settings, 'PLATFORM_BANK_ACCOUNT_NUMBER', '')
    rec_ifsc = rec_ifsc or getattr(settings, 'PLATFORM_BANK_IFSC', '')

    # Persist snapshot on Payment and link recipient user if available
    payment.recipient = recipient_user
    payment.recipient_upi_vpa = rec_upi
    payment.recipient_bank_holder_name = rec_holder
    payment.recipient_bank_account_number = rec_acc
    payment.recipient_bank_ifsc = rec_ifsc
    payment.provider = 'bank'
    payment.status = 'pending'
    payment.save(update_fields=[
        'recipient',
        'recipient_upi_vpa',
        'recipient_bank_holder_name',
        'recipient_bank_account_number',
        'recipient_bank_ifsc',
        'provider',
        'status',
    ])

    return render(request, 'auctions/bank_pay.html', {
        'payment': payment,
    })


@login_required
def bank_pay_confirm(request: HttpRequest, pk: int) -> HttpResponse:
    # Simple manual confirmation: user enters reference ID after transfer
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    if request.method != 'POST':
        return redirect('bank_pay_start', pk=pk)
    ref = (request.POST.get('reference') or '').strip()
    if not ref:
        messages.error(request, 'Reference/UTR is required.')
        return redirect('bank_pay_start', pk=pk)
    payment.provider_ref = ref
    payment.status = 'succeeded'
    payment.save(update_fields=['provider_ref', 'status'])
    apply_payment_effects(payment)
    # Messaging & redirects per purpose
    if payment.purpose == 'seat':
        messages.success(request, 'Seat booked successfully.')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose == 'penalty':
        messages.success(request, 'Penalty paid. You can continue bidding.')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose in ('order', 'buy_now'):
        messages.success(request, 'Payment successful!')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose == 'recharge':
        messages.success(request, 'Recharge successful! Funds added to wallet.')
        return redirect('wallet')
    messages.success(request, 'Payment recorded!')
    return redirect('wallet')


@login_required
def google_pay_callback(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    # Mark payment succeeded
    payment.status = 'succeeded'
    payment.save(update_fields=['status'])
    apply_payment_effects(payment)
    if payment.purpose == 'seat':
        messages.success(request, 'Seat booked successfully.')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose == 'penalty':
        messages.success(request, 'Penalty paid. You can continue bidding.')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose in ('order', 'buy_now'):
        messages.success(request, 'Payment successful!')
        return redirect('item_detail', pk=payment.item_id)
    if payment.purpose == 'recharge':
        messages.success(request, 'Recharge successful! Funds added to wallet.')
        return redirect('wallet')
    messages.success(request, 'Payment successful!')
    return redirect('item_detail', pk=payment.item_id)


def _generate_code(length: int = 8) -> str:
    """Generate a unique booking code, avoiding confusing characters."""
    # Avoid confusing characters like 0, O, 1, I, L
    chars = string.ascii_uppercase.replace('O', '').replace('I', '').replace('L', '') + \
            string.digits.replace('0', '').replace('1', '')
    return ''.join(random.choices(chars, k=length))


@login_required
def book_seat(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id == request.user.id:
        messages.error(request, 'Owners cannot book seats for their own items.')
        return redirect('item_detail', pk=pk)
    participant, _ = AuctionParticipant.objects.get_or_create(item=item, user=request.user)
    if participant.is_booked:
        messages.info(request, 'Seat already booked. Your code is available below.')
        return redirect('item_detail', pk=pk)

    # Enforce seat limit if set (>0)
    if item.seat_limit and item.participants.filter(is_booked=True, unbooked_at__isnull=True).count() >= item.seat_limit:
        messages.error(request, 'No seats available.')
        return redirect('item_detail', pk=pk)

    # Charge ₹5 seat booking; provider selection via ?provider=bank|gpay|crypto
    provider_param = (request.GET.get('provider') or 'gpay').lower()
    provider = 'google_pay'
    if provider_param in ('bank', 'upi', 'neft', 'imps'):
        provider = 'bank'
    elif provider_param in ('crypto', 'blockchain'):
        provider = 'blockchain'
    payment = Payment.objects.create(
        item=item,
        buyer=request.user,
        amount=Decimal('5.00'),
        purpose='seat',
        status='pending',
        provider=provider,
    )
    if provider == 'blockchain':
        return redirect('crypto_pay_start', pk=payment.pk)
    elif provider == 'bank':
        return redirect('bank_pay_start', pk=payment.pk)
    return redirect('google_pay_start', pk=payment.pk)



@login_required
def unbook_seat(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    participant = get_object_or_404(AuctionParticipant, item=item, user=request.user)
    if not participant.is_booked:
        messages.error(request, 'You do not have a booked seat.')
        return redirect('item_detail', pk=pk)
    # Allow unbook only within 1 minute of preview start
    if participant.preview_started_at is None:
        can_unbook = True
    else:
        can_unbook = timezone.now() <= participant.preview_started_at + timezone.timedelta(minutes=1)
    if not can_unbook:
        messages.error(request, 'Unbooking window is closed (only within 1 minute of preview).')
        return redirect('item_detail', pk=pk)
    participant.is_booked = False
    participant.unbooked_at = timezone.now()
    participant.code_verified_at = None
    participant.save(update_fields=['is_booked', 'unbooked_at', 'code_verified_at'])
    messages.success(request, 'Seat unbooked.')
    return redirect('item_detail', pk=pk)


@login_required
def join_with_code(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return redirect('home')
    code = request.POST.get('code', '').strip().upper()
    item_id = request.POST.get('item_id')
    item = get_object_or_404(AuctionItem, pk=item_id)
    # The code must belong to the logged-in user's participant record for this item
    participant = AuctionParticipant.objects.filter(item=item, user=request.user, booking_code=code).first()
    if not participant:
        messages.error(request, 'Invalid code for your account.')
        return redirect('item_detail', pk=item.pk)
    # Re-activate booking if previously unbooked
    participant.is_booked = True
    participant.unbooked_at = None
    participant.save(update_fields=['is_booked', 'unbooked_at'])
    # Persist verification on the participant record
    participant.code_verified_at = timezone.now()
    participant.save(update_fields=['code_verified_at'])
    messages.success(request, 'Code verified. You can join the video call now.')
    return redirect('item_detail', pk=item.pk)


@login_required
def start_preview(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id != request.user.id:
        messages.error(request, 'Only the owner can start preview.')
        return redirect('item_detail', pk=pk)
    now = timezone.now()
    AuctionParticipant.objects.filter(item=item, is_booked=True, unbooked_at__isnull=True).update(preview_started_at=now)
    messages.success(request, 'Preview started for all booked participants (10 minutes).')
    return redirect('item_detail', pk=pk)


@login_required
def start_call(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id != request.user.id:
        messages.error(request, 'Only the owner can start the call.')
        return redirect('item_detail', pk=pk)
    item.call_started_at = timezone.now()
    item.save(update_fields=['call_started_at'])
    messages.success(request, 'Live video call started.')
    return redirect('call_room', pk=pk)


@login_required
def call_room(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.call_started_at is None:
        messages.info(request, 'Call has not started yet.')
        return redirect('item_detail', pk=pk)

    # Seller can always join; others must have booked seat AND verified code in this session
    is_owner = (item.owner_id == request.user.id)
    if not is_owner:
        participant = AuctionParticipant.objects.filter(
            item=item,
            user=request.user,
            is_booked=True,
            unbooked_at__isnull=True,
        ).first()
        if not participant:
            messages.error(request, 'Only seat-booked users can join the call.')
            return redirect('item_detail', pk=pk)
        ap = AuctionParticipant.objects.filter(item=item, user=request.user).only('code_verified_at').first()
        if not (ap and ap.code_verified_at):
            messages.error(request, 'Enter your booking code to join the call.')
            return redirect('item_detail', pk=pk)
    return render(request, 'auctions/call.html', { 'item': item, 'is_owner': is_owner })


@login_required
def set_meet_link(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id != request.user.id:
        messages.error(request, 'Only the owner can update the Google Meet link.')
        return redirect('item_detail', pk=pk)
    if request.method != 'POST':
        return redirect('item_detail', pk=pk)

    raw_url = (request.POST.get('meet_url') or '').strip()
    if raw_url == '':
        # Allow clearing the link
        item.meet_url = ''
        item.save(update_fields=['meet_url'])
        messages.info(request, 'Google Meet link cleared.')
        return redirect('item_detail', pk=pk)

    try:
        parsed = urlparse(raw_url)
    except (ValueError, TypeError):
        parsed = None

    if not parsed or parsed.scheme not in ('http', 'https') or not parsed.netloc:
        messages.error(request, 'Please enter a valid URL like https://meet.google.com/abc-defg-hij')
        return redirect('item_detail', pk=pk)

    # Restrict to Google Meet domains only
    host = parsed.netloc.lower()
    if not (host == 'meet.google.com' or host.endswith('.meet.google.com')):
        messages.error(request, 'Only Google Meet links are allowed (https://meet.google.com/...).')
        return redirect('item_detail', pk=pk)

    item.meet_url = raw_url
    item.save(update_fields=['meet_url'])
    messages.success(request, 'Google Meet link updated.')
    return redirect('item_detail', pk=pk)


@login_required
def call_activity(request: HttpRequest, pk: int) -> JsonResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    is_owner = (item.owner_id == request.user.id)
    if not is_owner:
        participant = AuctionParticipant.objects.filter(
            item=item,
            user=request.user,
            is_booked=True,
            unbooked_at__isnull=True,
        ).first()
        if not participant:
            return JsonResponse({'error': 'forbidden'}, status=403)
        # Persisted check: require a verified code on the participant record
        ap = AuctionParticipant.objects.filter(item=item, user=request.user).only('code_verified_at').first()
        if not (ap and ap.code_verified_at):
            return JsonResponse({'error': 'forbidden'}, status=403)

    participants = list(
        AuctionParticipant.objects.filter(item=item, is_booked=True, unbooked_at__isnull=True)
        .select_related('user')
        .order_by('-last_seen_at')
        .values('user__username', 'booking_code', 'last_seen_at', 'penalty_due')
    )
    bids = list(
        item.bids.select_related('bidder')
        .order_by('-created_at')[:20]
        .values('bidder__username', 'amount', 'created_at', 'is_active')
    )
    return JsonResponse({
        'participants': participants,
        'bids': bids,
        'server_time': timezone.now().isoformat(),
    })


@require_GET
def public_bids(request: HttpRequest, pk: int) -> JsonResponse:
    """Public endpoint to show transparent bid history for an item.
    Includes bidder username, amount, timestamp, and whether active.
    """
    item = get_object_or_404(AuctionItem, pk=pk)
    bids = list(
        item.bids.select_related('bidder')
        .order_by('-created_at')[:100]
        .values('bidder__username', 'amount', 'created_at', 'is_active')
    )
    return JsonResponse({'item_id': item.pk, 'bids': bids, 'count': len(bids)})


@login_required
def verify(request: HttpRequest) -> HttpResponse:
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    # Handle email token via query param
    token = request.GET.get('email_token')
    if token and profile.email_verify_token and secrets.compare_digest(token, profile.email_verify_token):
        profile.email_verified_at = timezone.now()
        profile.email_verify_token = ''
        profile.save(update_fields=['email_verified_at', 'email_verify_token'])
        messages.success(request, 'Email verified successfully.')

    if request.method == 'POST':
        code = request.POST.get('otp', '').strip()
        if profile.phone_otp_code and secrets.compare_digest(code, profile.phone_otp_code):
            profile.phone_verified_at = timezone.now()
            profile.phone_otp_code = ''
            profile.save(update_fields=['phone_verified_at', 'phone_otp_code'])
            messages.success(request, 'Phone number verified successfully.')
        else:
            messages.error(request, 'Invalid OTP. Please try again.')

    return render(request, 'auctions/verify.html', {
        'profile': profile,
    })


@login_required
def resend_phone_otp(request: HttpRequest) -> HttpResponse:
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.phone_otp_code = ''.join(random.choices(string.digits, k=6))
    profile.save(update_fields=['phone_otp_code'])
    messages.info(request, f"New OTP generated: {profile.phone_otp_code}")
    return redirect('verify')


@login_required
@require_POST
def presence_ping(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    participant, _ = AuctionParticipant.objects.get_or_create(item=item, user=request.user)
    participant.last_seen_at = timezone.now()
    participant.save(update_fields=['last_seen_at'])

    # Check if current highest bidder is offline; if so, penalize and deactivate their bids
    highest = item.bids.filter(is_active=True).order_by('-amount', 'created_at').first()
    if highest:
        highest_part = AuctionParticipant.objects.filter(item=item, user=highest.bidder).first()
        if highest_part and highest_part.last_seen_at:
            offline_for = timezone.now() - highest_part.last_seen_at
            if offline_for.total_seconds() > 30 and not highest_part.penalty_due:
                # Create penalty payment
                penalty_payment = Payment.objects.create(
                    item=item,
                    buyer=highest.bidder,
                    amount=Decimal('200.00'),
                    purpose='penalty',
                    status='pending',
                )
                highest_part.penalty_due = True
                highest_part.save(update_fields=['penalty_due'])
                # Deactivate their active bids
                item.bids.filter(bidder=highest.bidder, is_active=True).update(is_active=False)
                # Release any active hold on this item for that user
                hold = WalletHold.objects.filter(item=item, user=highest.bidder, status='active').first()
                if hold:
                    hold.status = 'released'
                    hold.save(update_fields=['status', 'updated_at'])
                    prev_wallet = get_or_create_wallet(highest.bidder)
                    WalletTransaction.objects.create(
                        user=highest.bidder,
                        item=item,
                        kind='hold_release',
                        amount=hold.amount,
                        balance_after=prev_wallet.balance,
                    )
                append_ledger_block({
                    'type': 'penalty_assessed',
                    'item_id': item.pk,
                    'user_id': highest.bidder.pk,
                    'payment_id': penalty_payment.pk,
                    'amount': str(penalty_payment.amount),
                    'timestamp': timezone.now().isoformat(),
                })
    return HttpResponse('ok')


@login_required
def pay_penalty(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    participant = get_object_or_404(AuctionParticipant, item=item, user=request.user)
    if not participant.penalty_due:
        messages.info(request, 'No penalty due.')
        return redirect('item_detail', pk=pk)
    provider_param = (request.GET.get('provider') or 'gpay').lower()
    provider = 'google_pay'
    if provider_param in ('bank', 'upi', 'neft', 'imps'):
        provider = 'bank'
    elif provider_param in ('crypto', 'blockchain'):
        provider = 'blockchain'
    payment = Payment.objects.filter(
        item=item, buyer=request.user, purpose='penalty', status__in=['pending', 'processing']
    ).order_by('-created_at').first()
    if not payment:
        payment = Payment.objects.create(
            item=item,
            buyer=request.user,
            amount=Decimal('200.00'),
            purpose='penalty',
            status='pending',
            provider=provider,
        )
    if provider == 'blockchain':
        return redirect('crypto_pay_start', pk=payment.pk)
    elif provider == 'bank':
        return redirect('bank_pay_start', pk=payment.pk)
    return redirect('google_pay_start', pk=payment.pk)

@login_required
def crypto_pay_start(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    if payment.provider != 'blockchain':
        return redirect('google_pay_start', pk=pk)
    if not getattr(settings, 'BLOCKCHAIN_ENABLED', True):
        messages.error(request, 'Blockchain payments disabled.')
        return redirect('item_detail', pk=payment.item_id)
    quote = inr_to_token_quote(Decimal(payment.amount))
    payment.onchain_amount_wei = str(quote.wei_amount)
    payment.token_symbol = quote.token_symbol
    payment.chain = getattr(settings, 'BLOCKCHAIN_NETWORK_NAME', 'polygon')
    payment.onchain_status = 'pending'
    payment.save(update_fields=['onchain_amount_wei', 'token_symbol', 'chain', 'onchain_status'])
    return render(request, 'auctions/crypto_pay.html', {
        'payment': payment,
        'quote': quote,
        'merchant_address': getattr(settings, 'BLOCKCHAIN_MERCHANT_ADDRESS', ''),
        'network_name': getattr(settings, 'BLOCKCHAIN_NETWORK_NAME', 'polygon'),
        'min_confirmations': int(getattr(settings, 'BLOCKCHAIN_MIN_CONFIRMATIONS', 3)),
    })


@login_required
def crypto_pay_confirm(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    if payment.provider != 'blockchain':
        return redirect('item_detail', pk=payment.item_id)
    tx_hash = (request.POST.get('tx_hash') or '').strip()
    payer_address = (request.POST.get('from_address') or '').strip()
    if not tx_hash:
        messages.error(request, 'Transaction hash is required.')
        return redirect('crypto_pay_start', pk=pk)
    expected_to = payment.recipient_address or getattr(settings, 'BLOCKCHAIN_MERCHANT_ADDRESS', '')
    expected_wei = int(payment.onchain_amount_wei or '0')
    result = validate_native_transfer(tx_hash, expected_to, expected_wei)
    payment.tx_hash = tx_hash
    payment.payer_address = payer_address
    payment.confirmations = int(result.get('confirmations', 0))
    payment.onchain_status = 'confirmed' if result.get('ok') else 'pending'
    if result.get('ok'):
        payment.status = 'succeeded' if result.get('confirmed') else 'processing'
    payment.save(update_fields=['tx_hash', 'payer_address', 'confirmations', 'onchain_status', 'status'])

    if result.get('ok'):
        apply_payment_effects(payment)
        if payment.purpose == 'seat':
            messages.success(request, 'Seat booked successfully.')
            return redirect('item_detail', pk=payment.item_id)
        if payment.purpose == 'penalty':
            messages.success(request, 'Penalty paid. You can continue bidding.')
            return redirect('item_detail', pk=payment.item_id)
        if payment.purpose in ('order', 'buy_now'):
            messages.success(request, 'Payment successful!')
            return redirect('item_detail', pk=payment.item_id)
        if payment.purpose == 'recharge':
            messages.success(request, 'Recharge successful! Funds added to wallet.')
            return redirect('wallet')
    else:
        messages.info(request, 'Waiting for confirmations. Please refresh later.')
        return redirect('crypto_pay_start', pk=pk)


@login_required
def settle(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.owner_id != request.user.id and not request.user.is_staff:
        messages.error(request, 'Not allowed.')
        return redirect('item_detail', pk=pk)
    if item.is_settled:
        messages.info(request, 'Item already settled.')
        return redirect('item_detail', pk=pk)
    if timezone.now() < item.ends_at:
        messages.error(request, 'Auction not ended yet.')
        return redirect('item_detail', pk=pk)
    highest = item.bids.filter(is_active=True).order_by('-amount', 'created_at').first()
    if not highest:
        item.is_settled = True
        item.is_active = False
        item.save(update_fields=['is_settled', 'is_active'])
        messages.info(request, 'No bids. Auction closed.')
        return redirect('item_detail', pk=pk)

    from .utils import settle_auction_item
    ok = settle_auction_item(item)

    if ok:
        messages.success(request, 'Winner charged automatically and order created.')
    else:
        messages.info(request, 'Item already settled or not eligible.')
    return redirect('item_detail', pk=pk)


@login_required
def history(request: HttpRequest) -> HttpResponse:
    """Show the authenticated user's activity history."""
    orders = Order.objects.filter(buyer=request.user).order_by('-created_at')
    payments = Payment.objects.filter(buyer=request.user).order_by('-created_at')
    bids = Bid.objects.filter(bidder=request.user).select_related('item').order_by('-created_at')
    return render(request, 'auctions/history.html', {
        'orders': orders,
        'payments': payments,
        'bids': bids,
    })


@login_required
def wallet_view(request: HttpRequest) -> HttpResponse:
    wallet = get_or_create_wallet(request.user)
    from .models import WalletHold, WalletTransaction, UserProfile
    holds = WalletHold.objects.filter(user=request.user).select_related('item').order_by('-created_at')
    transactions = WalletTransaction.objects.filter(user=request.user).select_related('item', 'payment').order_by('-created_at')[:100]
    available = get_available_balance(request.user)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    bank_accounts = BankAccount.objects.filter(user=request.user).order_by('-created_at')
    bank_form = BankLinkForm()
    return render(request, 'auctions/wallet.html', {
        'wallet': wallet,
        'available': available,
        'holds': holds,
        'transactions': transactions,
        'profile': profile,
        'bank_accounts': bank_accounts,
        'bank_form': bank_form,
    })


@login_required
def wallet_recharge(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return redirect('wallet')
    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except (ValueError, TypeError, InvalidOperation):
        messages.error(request, 'Invalid amount.')
        return redirect('wallet')
    # Per-transaction recharge limit (₹10,000)
    if amount > Decimal('10000.00'):
        messages.error(request, 'Recharge limit per transaction is ₹10,000.')
        return redirect('wallet')
    if amount <= 0:
        messages.error(request, 'Amount must be positive.')
        return redirect('wallet')
    if amount < Decimal('1.00'):
        messages.error(request, 'Minimum recharge amount is ₹1.00.')
        return redirect('wallet')
    method = (request.POST.get('method') or 'upi').lower()
    provider = 'google_pay'
    if method == 'card':
        provider = 'card'
    elif method == 'bank':
        provider = 'bank'
    elif method == 'crypto':
        provider = 'blockchain'

    with transaction.atomic():
        payment = Payment.objects.create(
            item=None,
            buyer=request.user,
            amount=amount,
            purpose='recharge',
            status='pending',
            provider=provider,
        )
    if provider == 'blockchain':
        return redirect('crypto_pay_start', pk=payment.pk)
    elif provider == 'bank':
        return redirect('bank_pay_start', pk=payment.pk)
    else:
        return redirect('google_pay_start', pk=payment.pk)


@login_required
def update_payment_methods(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return redirect('wallet')
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    # Update simple fields; basic sanitization
    upi_vpa = (request.POST.get('upi_vpa') or '').strip()
    bank_holder_name = (request.POST.get('bank_holder_name') or '').strip()
    bank_account_number = (request.POST.get('bank_account_number') or '').strip()
    bank_ifsc = (request.POST.get('bank_ifsc') or '').strip().upper()
    auto_debit_raw = request.POST.get('auto_debit_consent')

    changed = False
    if upi_vpa != profile.upi_vpa:
        profile.upi_vpa = upi_vpa
        changed = True
    if bank_holder_name != profile.bank_holder_name:
        profile.bank_holder_name = bank_holder_name
        changed = True
    if bank_account_number != profile.bank_account_number:
        profile.bank_account_number = bank_account_number
        changed = True
    if bank_ifsc != profile.bank_ifsc:
        profile.bank_ifsc = bank_ifsc
        changed = True
    # Check auto-debit checkbox
    auto_debit = bool(auto_debit_raw)
    if profile.auto_debit_consent != auto_debit:
        profile.auto_debit_consent = auto_debit
        changed = True

    if changed:
        profile.save(update_fields=['upi_vpa', 'bank_holder_name', 'bank_account_number', 'bank_ifsc'])
        messages.success(request, 'Payment methods updated.')
    else:
        messages.info(request, 'No changes detected.')
    return redirect('wallet')


@login_required
def link_bank(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return redirect('wallet')
    form = BankLinkForm(request.POST)
    if form.is_valid():
        BankAccount.objects.create(
            user=request.user,
            bank_name=form.cleaned_data['bank_name'],
            account_number=form.cleaned_data['account_number'],
            ifsc=form.cleaned_data['ifsc'],
            deposit_instructions=form.cleaned_data.get('deposit_instructions', ''),
        )
        messages.success(request, 'Bank account added.')
    else:
        messages.error(request, 'Please correct the bank details.')
    return redirect('wallet')


@login_required
def export_user_data(request: HttpRequest) -> HttpResponse:
    """Export all user data as a downloadable JSON file"""
    user = request.user
    
    # Get all user data
    user_data = {
        'export_timestamp': timezone.now().isoformat(),
        'user_info': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_joined': user.date_joined.isoformat() if user.date_joined else None,
            'last_login': user.last_login.isoformat() if user.last_login else None,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
        },
        'profile': self.serialize_model_data(
            UserProfile.objects.filter(user=user)
        ),
        'wallet': self.serialize_model_data(
            Wallet.objects.filter(user=user)
        ),
        'wallet_transactions': self.serialize_model_data(
            WalletTransaction.objects.filter(user=user)
        ),
        'wallet_holds': self.serialize_model_data(
            WalletHold.objects.filter(user=user)
        ),
        'owned_items': self.serialize_model_data(
            AuctionItem.objects.filter(owner=user)
        ),
        'bids': self.serialize_model_data(
            Bid.objects.filter(bidder=user)
        ),
        'payments': self.serialize_model_data(
            Payment.objects.filter(buyer=user)
        ),
        'payments_received': self.serialize_model_data(
            Payment.objects.filter(recipient=user)
        ),
        'orders': self.serialize_model_data(
            Order.objects.filter(buyer=user)
        ),
        'auction_participations': self.serialize_model_data(
            AuctionParticipant.objects.filter(user=user)
        ),
    }
    
    # Create JSON response
    response = HttpResponse(
        json.dumps(user_data, indent=2, default=str),
        content_type='application/json'
    )
    response['Content-Disposition'] = f'attachment; filename="user_data_{user.username}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
    
    return response


def serialize_model_data(queryset):
    """Serialize model data to dictionary format"""
    data = []
    for obj in queryset:
        obj_dict = {}
        for field in obj._meta.fields:
            value = getattr(obj, field.name)
            if hasattr(value, 'isoformat'):  # Handle datetime fields
                obj_dict[field.name] = value.isoformat()
            else:
                obj_dict[field.name] = value
        data.append(obj_dict)
    return data