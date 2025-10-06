from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import HttpRequest, HttpResponse
from django import forms

from .models import AuctionItem, Bid, Payment, AuctionParticipant
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
        ]


def home(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    items = AuctionItem.objects.filter(ends_at__gt=now).order_by('ends_at')
    return render(request, 'auctions/home.html', {'items': items})


def register_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful!')
            return redirect('home')
    else:
        form = UserCreationForm()
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
    bids = item.bids.select_related('bidder').all()
    return render(request, 'auctions/item_detail.html', {
        'item': item,
        'bids': bids,
    })


@login_required
def place_bid(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(AuctionItem, pk=pk)
    if not item.can_accept_bids():
        messages.error(request, 'Bidding is closed for this item.')
        return redirect('item_detail', pk=pk)

    # Ensure the user is registered as a participant before enforcing min participants
    AuctionParticipant.objects.get_or_create(item=item, user=request.user)

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

    Bid.objects.create(item=item, bidder=request.user, amount=amount)
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

# Create your views here.
