from decimal import Decimal
import random
import string
import secrets
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import HttpRequest, HttpResponse, JsonResponse
from django import forms
from django.db import transaction

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
)
from urllib.parse import urlparse
from .utils import append_ledger_block, get_available_balance, get_or_create_wallet
from django.conf import settings
from .blockchain import inr_to_token_quote, validate_native_transfer


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
    return render(request, 'auctions/item_detail.html', {
        'item': item,
        'bids': bids,
        'participant': participant,
        'has_verified_code': has_verified_code,
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
    except Exception:
        messages.error(request, 'Invalid bid amount.')
        return redirect('item_detail', pk=pk)

    min_allowed = item.starting_price
    if item.highest_bid:
        min_allowed = max(min_allowed, item.highest_bid.amount + Decimal('1.00'))

    if amount < min_allowed:
        messages.error(request, f'Bid must be at least {min_allowed}.')
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

        # Reserve/adjust hold for this user
        wallet = get_or_create_wallet(request.user)
        hold = WalletHold.objects.select_for_update().filter(item=item_refreshed, user=request.user, status='active').first()
        if hold:
            delta = amount - hold.amount
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

        Bid.objects.create(item=item_refreshed, bidder=request.user, amount=amount, is_active=True)
        append_ledger_block({
            'type': 'bid_placed',
            'item_id': item_refreshed.pk,
            'user_id': request.user.pk,
            'amount': str(amount),
            'timestamp': timezone.now().isoformat(),
        })

    messages.success(request, 'Bid placed! Funds reserved until you are outbid or auction ends.')
    return redirect('item_detail', pk=pk)


@login_required
def buy_now(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.buy_now_price is None:
        messages.error(request, 'Buy now is not available for this item.')
        return redirect('item_detail', pk=pk)
    # Always use Google Pay for buy now
    payment = Payment.objects.create(
        item=item,
        buyer=request.user,
        amount=item.buy_now_price,
        purpose='buy_now',
        provider='google_pay',
        status='pending',
    )
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
def google_pay_callback(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(Payment, pk=pk, buyer=request.user)
    # Mark payment succeeded
    payment.status = 'succeeded'
    payment.save(update_fields=['status'])

    # Post-payment effects similar to on-chain confirmation flow
    if payment.purpose == 'seat':
        participant = AuctionParticipant.objects.get(item=payment.item, user=request.user)
        participant.is_booked = True
        participant.paid = True
        participant.paid_at = timezone.now()
        # Ensure code uniqueness within this item
        code = _generate_code()
        while AuctionParticipant.objects.filter(item=payment.item, booking_code=code).exists():
            code = _generate_code()
        participant.booking_code = code
        participant.save()
        append_ledger_block({
            'type': 'seat_booking',
            'item_id': payment.item_id,
            'user_id': request.user.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'provider_ref': payment.provider_ref,
            'timestamp': timezone.now().isoformat(),
        })
        messages.success(request, f'Seat booked. Your code: {participant.booking_code}')
        return redirect('item_detail', pk=payment.item_id)
    elif payment.purpose == 'penalty':
        participant = AuctionParticipant.objects.get(item=payment.item, user=request.user)
        participant.penalty_due = False
        participant.save(update_fields=['penalty_due'])
        append_ledger_block({
            'type': 'penalty_paid',
            'item_id': payment.item_id,
            'user_id': request.user.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'provider_ref': payment.provider_ref,
            'timestamp': timezone.now().isoformat(),
        })
        messages.success(request, 'Penalty paid. You can continue bidding.')
        return redirect('item_detail', pk=payment.item_id)
    elif payment.purpose in ('order', 'buy_now'):
        Order.objects.update_or_create(
            item=payment.item,
            buyer=request.user,
            defaults={
                'amount': payment.amount,
                'status': 'paid',
                'paid_at': timezone.now(),
            }
        )
        append_ledger_block({
            'type': 'order_paid',
            'item_id': payment.item_id,
            'buyer_id': request.user.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'provider_ref': payment.provider_ref,
            'timestamp': timezone.now().isoformat(),
        })
        messages.success(request, 'Payment successful!')
        return redirect('item_detail', pk=payment.item_id)
    elif payment.purpose == 'recharge':
        # Credit wallet balance
        wallet = get_or_create_wallet(request.user)
        wallet.balance = (wallet.balance or Decimal('0')) + Decimal(payment.amount)
        wallet.save(update_fields=['balance'])
        WalletTransaction.objects.create(
            user=request.user,
            payment=payment,
            kind='credit',
            amount=payment.amount,
            balance_after=wallet.balance,
        )
        append_ledger_block({
            'type': 'wallet_recharge',
            'user_id': request.user.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'provider_ref': payment.provider_ref,
            'timestamp': timezone.now().isoformat(),
        })
        messages.success(request, 'Recharge successful! Funds added to wallet.')
        return redirect('wallet')
    else:
        # Fallback generic record
        append_ledger_block({
            'type': 'payment',
            'payment_id': payment.pk,
            'item_id': payment.item_id,
            'buyer_id': payment.buyer_id,
            'amount': str(payment.amount),
            'provider_ref': payment.provider_ref,
            'timestamp': timezone.now().isoformat(),
        })
        messages.success(request, 'Payment successful!')
        return redirect('item_detail', pk=payment.item_id)


def _generate_code(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


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

    # Charge ₹5 seat booking via Google Pay
    payment = Payment.objects.create(
        item=item,
        buyer=request.user,
        amount=Decimal('5.00'),
        purpose='seat',
        status='pending',
        provider='google_pay',
    )
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
    except Exception:
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
            provider='google_pay',
        )
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
        # Post-payment effects
        if payment.purpose == 'seat':
            participant = AuctionParticipant.objects.get(item=payment.item, user=request.user)
            participant.is_booked = True
            participant.paid = True
            participant.paid_at = timezone.now()
            code = _generate_code()
            while AuctionParticipant.objects.filter(item=payment.item, booking_code=code).exists():
                code = _generate_code()
            participant.booking_code = code
            participant.save()
            append_ledger_block({
                'type': 'seat_booking',
                'item_id': payment.item_id,
                'user_id': request.user.pk,
                'payment_id': payment.pk,
                'amount': str(payment.amount),
                'tx_hash': payment.tx_hash,
                'timestamp': timezone.now().isoformat(),
            })
            messages.success(request, f'Seat booked. Your code: {participant.booking_code}')
            return redirect('item_detail', pk=payment.item_id)
        elif payment.purpose == 'penalty':
            participant = AuctionParticipant.objects.get(item=payment.item, user=request.user)
            participant.penalty_due = False
            participant.save(update_fields=['penalty_due'])
            append_ledger_block({
                'type': 'penalty_paid',
                'item_id': payment.item_id,
                'user_id': request.user.pk,
                'payment_id': payment.pk,
                'amount': str(payment.amount),
                'tx_hash': payment.tx_hash,
                'timestamp': timezone.now().isoformat(),
            })
            messages.success(request, 'Penalty paid. You can continue bidding.')
            return redirect('item_detail', pk=payment.item_id)
        elif payment.purpose in ('order', 'buy_now'):
            Order.objects.update_or_create(
                item=payment.item,
                buyer=request.user,
                defaults={
                    'amount': payment.amount,
                    'status': 'paid',
                    'paid_at': timezone.now(),
                }
            )
            append_ledger_block({
                'type': 'order_paid',
                'item_id': payment.item_id,
                'buyer_id': request.user.pk,
                'payment_id': payment.pk,
                'amount': str(payment.amount),
                'tx_hash': payment.tx_hash,
                'timestamp': timezone.now().isoformat(),
            })
            messages.success(request, 'Payment successful!')
            return redirect('item_detail', pk=payment.item_id)
        elif payment.purpose == 'recharge':
            wallet = get_or_create_wallet(request.user)
            wallet.balance = (wallet.balance or Decimal('0')) + Decimal(payment.amount)
            wallet.save(update_fields=['balance'])
            WalletTransaction.objects.create(
                user=request.user,
                payment=payment,
                kind='credit',
                amount=payment.amount,
                balance_after=wallet.balance,
            )
            append_ledger_block({
                'type': 'wallet_recharge',
                'user_id': request.user.pk,
                'payment_id': payment.pk,
                'amount': str(payment.amount),
                'tx_hash': payment.tx_hash,
                'timestamp': timezone.now().isoformat(),
            })
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

    with transaction.atomic():
        # Consume hold if available, else fall back to bank debit simulation
        wallet = get_or_create_wallet(highest.bidder)
        hold = WalletHold.objects.select_for_update().filter(item=item, user=highest.bidder, status='active').first()
        paid_via = 'wallet'
        if hold and wallet.balance >= hold.amount:
            wallet.balance = (wallet.balance or Decimal('0')) - hold.amount
            wallet.save(update_fields=['balance'])
            hold.status = 'consumed'
            hold.save(update_fields=['status', 'updated_at'])
            WalletTransaction.objects.create(
                user=highest.bidder,
                item=item,
                kind='hold_consume',
                amount=hold.amount,
                balance_after=wallet.balance,
            )
        else:
            paid_via = 'bank'

        order = Order.objects.create(item=item, buyer=highest.bidder, amount=highest.amount, status='paid', paid_at=timezone.now())
        payment = Payment.objects.create(
            item=item,
            buyer=highest.bidder,
            amount=highest.amount,
            purpose='order',
            status='succeeded',
            provider='bank' if paid_via == 'bank' else 'wallet',
            provider_ref=f"ORD-{order.pk}"
        )
        append_ledger_block({
            'type': 'order_paid',
            'item_id': item.pk,
            'buyer_id': highest.bidder.pk,
            'order_id': order.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'paid_via': paid_via,
            'timestamp': timezone.now().isoformat(),
        })
        item.is_settled = True
        item.is_active = False
        item.save(update_fields=['is_settled', 'is_active'])

    messages.success(request, 'Winner charged automatically and order created.')
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
    return render(request, 'auctions/wallet.html', {
        'wallet': wallet,
        'available': available,
        'holds': holds,
        'transactions': transactions,
        'profile': profile,
    })


@login_required
def wallet_recharge(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return redirect('wallet')
    try:
        amount = Decimal(request.POST.get('amount', '0'))
    except Exception:
        messages.error(request, 'Invalid amount.')
        return redirect('wallet')
    if amount <= 0:
        messages.error(request, 'Amount must be positive.')
        return redirect('wallet')
    method = (request.POST.get('method') or 'upi').lower()
    provider = 'google_pay'
    if method == 'card':
        provider = 'card'
    elif method == 'bank':
        provider = 'bank'
    elif method == 'crypto':
        provider = 'blockchain'

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
    if changed:
        profile.save(update_fields=['upi_vpa', 'bank_holder_name', 'bank_account_number', 'bank_ifsc'])
        messages.success(request, 'Payment methods updated.')
    else:
        messages.info(request, 'No changes detected.')
    return redirect('wallet')
