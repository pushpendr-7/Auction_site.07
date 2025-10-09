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

from .models import AuctionItem, Bid, Payment, AuctionParticipant, Order, UserProfile
from urllib.parse import urlparse
from .utils import append_ledger_block


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

    Bid.objects.create(item=item, bidder=request.user, amount=amount, is_active=True)
    messages.success(request, 'Bid placed!')
    return redirect('item_detail', pk=pk)


@login_required
def buy_now(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if item.buy_now_price is None:
        messages.error(request, 'Buy now is not available for this item.')
        return redirect('item_detail', pk=pk)
    payment = Payment.objects.create(item=item, buyer=request.user, amount=item.buy_now_price)
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
    payment.status = 'succeeded'
    payment.save()
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
    return redirect('item_detail', pk=payment.item.pk)


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

    # Charge ₹5 seat booking
    payment = Payment.objects.create(item=item, buyer=request.user, amount=Decimal('5.00'), purpose='seat', status='processing')
    payment.provider_ref = f"SEAT-{payment.pk}"
    payment.status = 'succeeded'
    payment.save()
    append_ledger_block({
        'type': 'seat_booking',
        'item_id': item.pk,
        'user_id': request.user.pk,
        'payment_id': payment.pk,
        'amount': str(payment.amount),
        'timestamp': timezone.now().isoformat(),
    })
    participant.is_booked = True
    participant.paid = True
    participant.paid_at = timezone.now()
    # Ensure code uniqueness within this item
    code = _generate_code()
    while AuctionParticipant.objects.filter(item=item, booking_code=code).exists():
        code = _generate_code()
    participant.booking_code = code
    participant.save()
    messages.success(request, f'Seat booked successfully. Your code: {participant.booking_code}')
    return redirect('item_detail', pk=pk)


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
        try:
            verified_items = {int(x) for x in request.session.get('verified_items', [])}
        except Exception:
            verified_items = set()
        if int(item.pk) not in verified_items:
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
    payment = Payment.objects.filter(item=item, buyer=request.user, purpose='penalty', status__in=['pending', 'processing']).order_by('-created_at').first()
    if not payment:
        payment = Payment.objects.create(item=item, buyer=request.user, amount=Decimal('200.00'), purpose='penalty', status='processing')
    payment.provider_ref = f"PEN-{payment.pk}"
    payment.status = 'succeeded'
    payment.save()
    append_ledger_block({
        'type': 'penalty_paid',
        'item_id': item.pk,
        'user_id': request.user.pk,
        'payment_id': payment.pk,
        'amount': str(payment.amount),
        'timestamp': timezone.now().isoformat(),
    })
    participant.penalty_due = False
    participant.save(update_fields=['penalty_due'])
    messages.success(request, 'Penalty paid. You can continue bidding.')
    return redirect('item_detail', pk=pk)


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

    order = Order.objects.create(item=item, buyer=highest.bidder, amount=highest.amount, status='paid', paid_at=timezone.now())
    payment = Payment.objects.create(item=item, buyer=highest.bidder, amount=highest.amount, purpose='order', status='succeeded', provider_ref=f"ORD-{order.pk}")
    append_ledger_block({
        'type': 'order_paid',
        'item_id': item.pk,
        'buyer_id': highest.bidder.pk,
        'order_id': order.pk,
        'payment_id': payment.pk,
        'amount': str(payment.amount),
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
