import hashlib
from typing import Dict, Any
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import (
    LedgerBlock,
    Wallet,
    WalletHold,
    Payment,
    AuctionParticipant,
    Order,
)


def compute_hash(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def append_ledger_block(data: Dict[str, Any]) -> LedgerBlock:
    with transaction.atomic():
        last_block = LedgerBlock.objects.order_by('-index').first()
        index = 0 if last_block is None else last_block.index + 1
        previous_hash = '0' * 64 if last_block is None else last_block.hash
        payload = f"{index}|{previous_hash}|{data}"
        block_hash = compute_hash(payload)
        block = LedgerBlock.objects.create(
            index=index,
            previous_hash=previous_hash,
            data=data,
            hash=block_hash,
        )
        return block


def get_or_create_wallet(user) -> Wallet:
    """Return a wallet for the user, creating if missing."""
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def get_active_holds_total(user) -> Decimal:
    """Sum of active holds across all items for the user."""
    agg = WalletHold.objects.filter(user=user, status='active').aggregate(total=Sum('amount'))
    total = agg.get('total') or Decimal('0')
    return Decimal(total)


def get_available_balance(user) -> Decimal:
    """User's spendable balance, excluding active holds."""
    wallet = get_or_create_wallet(user)
    holds_total = get_active_holds_total(user)
    balance = wallet.balance or Decimal('0')
    available = balance - holds_total
    return max(available, Decimal('0'))  # Ensure non-negative balance


def apply_payment_effects(payment: Payment) -> bool:
    """Idempotently apply post-payment effects.
    Returns True if effects were applied in this call, False if already processed.
    """
    with transaction.atomic():
        fresh = Payment.objects.select_for_update().get(pk=payment.pk)
        if fresh.processed_at:
            return False

        # Mark processed upfront to enforce idempotency even if subsequent steps repeat
        fresh.processed_at = timezone.now()
        fresh.save(update_fields=['processed_at'])

        # Seat booking
        if fresh.purpose == 'seat' and fresh.item_id and fresh.buyer_id:
            participant = AuctionParticipant.objects.get(item_id=fresh.item_id, user_id=fresh.buyer_id)
            participant.is_booked = True
            participant.paid = True
            participant.paid_at = timezone.now()
            # Ensure unique code per item
            from .views import _generate_code  # local import to avoid cycles at module import
            code = _generate_code()
            while AuctionParticipant.objects.filter(item_id=fresh.item_id, booking_code=code).exists():
                code = _generate_code()
            participant.booking_code = code
            participant.save()
            append_ledger_block({
                'type': 'seat_booking',
                'item_id': fresh.item_id,
                'user_id': fresh.buyer_id,
                'payment_id': fresh.pk,
                'amount': str(fresh.amount),
                'provider_ref': fresh.provider_ref,
                'tx_hash': fresh.tx_hash,
                'transaction_id': fresh.transaction_id,
                'timestamp': timezone.now().isoformat(),
            })

        # Penalty clear
        elif fresh.purpose == 'penalty' and fresh.item_id and fresh.buyer_id:
            participant = AuctionParticipant.objects.get(item_id=fresh.item_id, user_id=fresh.buyer_id)
            participant.penalty_due = False
            participant.save(update_fields=['penalty_due'])
            append_ledger_block({
                'type': 'penalty_paid',
                'item_id': fresh.item_id,
                'user_id': fresh.buyer_id,
                'payment_id': fresh.pk,
                'amount': str(fresh.amount),
                'provider_ref': fresh.provider_ref,
                'tx_hash': fresh.tx_hash,
                'transaction_id': fresh.transaction_id,
                'timestamp': timezone.now().isoformat(),
            })

        # Order or buy-now
        elif fresh.purpose in ('order', 'buy_now') and fresh.item_id and fresh.buyer_id:
            Order.objects.update_or_create(
                item_id=fresh.item_id,
                buyer_id=fresh.buyer_id,
                defaults={'amount': fresh.amount, 'status': 'paid', 'paid_at': timezone.now()},
            )
            append_ledger_block({
                'type': 'order_paid',
                'item_id': fresh.item_id,
                'buyer_id': fresh.buyer_id,
                'payment_id': fresh.pk,
                'amount': str(fresh.amount),
                'provider_ref': fresh.provider_ref,
                'tx_hash': fresh.tx_hash,
                'transaction_id': fresh.transaction_id,
                'timestamp': timezone.now().isoformat(),
            })

        # Wallet recharge
        elif fresh.purpose == 'recharge' and fresh.buyer_id:
            wallet = get_or_create_wallet(fresh.buyer)
            wallet.balance = (wallet.balance or Decimal('0')) + Decimal(fresh.amount)
            wallet.save(update_fields=['balance'])
            from .models import WalletTransaction
            WalletTransaction.objects.create(
                user=fresh.buyer,
                payment=fresh,
                kind='credit',
                amount=fresh.amount,
                balance_after=wallet.balance,
            )
            append_ledger_block({
                'type': 'wallet_recharge',
                'user_id': fresh.buyer_id,
                'payment_id': fresh.pk,
                'amount': str(fresh.amount),
                'provider_ref': fresh.provider_ref,
                'tx_hash': fresh.tx_hash,
                'transaction_id': fresh.transaction_id,
                'timestamp': timezone.now().isoformat(),
            })

        else:
            # Generic record for unknown purpose
            append_ledger_block({
                'type': 'payment',
                'payment_id': fresh.pk,
                'item_id': fresh.item_id,
                'buyer_id': fresh.buyer_id,
                'amount': str(fresh.amount),
                'provider_ref': fresh.provider_ref,
                'tx_hash': fresh.tx_hash,
                'transaction_id': fresh.transaction_id,
                'timestamp': timezone.now().isoformat(),
            })

        return True


def settle_auction_item(item) -> bool:
    """Idempotently settle a single ended auction item.
    Returns True if settlement happened, False otherwise.
    """
    from .models import WalletTransaction, WalletHold
    from django.contrib.auth import get_user_model
    from .models import UserProfile

    with transaction.atomic():
        fresh_item = type(item).objects.select_for_update().get(pk=item.pk)
        if fresh_item.is_settled:
            return False
        if timezone.now() < fresh_item.ends_at:
            return False
        highest = fresh_item.bids.filter(is_active=True).order_by('-amount', 'created_at').first()
        if not highest:
            fresh_item.is_settled = True
            fresh_item.is_active = False
            fresh_item.save(update_fields=['is_settled', 'is_active'])
            return True

        # Try to consume hold; fallback to auto-debit if user consented
        wallet = get_or_create_wallet(highest.bidder)
        hold = WalletHold.objects.select_for_update().filter(
            item=fresh_item, user=highest.bidder, status='active'
        ).first()
        paid_via = 'wallet'
        amount = highest.amount
        
        try:
            if hold and wallet.balance >= hold.amount:
                wallet.balance = (wallet.balance or Decimal('0')) - hold.amount
                wallet.save(update_fields=['balance'])
                hold.status = 'consumed'
                hold.save(update_fields=['status', 'updated_at'])
                WalletTransaction.objects.create(
                    user=highest.bidder,
                    item=fresh_item,
                    kind='hold_consume',
                    amount=hold.amount,
                    balance_after=wallet.balance,
                )
            else:
                # Simulate auto-debit only if explicitly consented by user
                profile, _ = UserProfile.objects.get_or_create(user=highest.bidder)
                if profile.auto_debit_consent:
                    paid_via = 'bank'
                else:
                    # Without consent, leave payment pending for manual completion
                    paid_via = 'bank_pending'
        except Exception as e:
            # Log error and fallback to manual payment
            print(f"Error processing wallet payment for user {highest.bidder.id}: {e}")
            paid_via = 'bank_pending'

        order = Order.objects.create(
            item=fresh_item,
            buyer=highest.bidder,
            amount=amount,
            status='paid' if paid_via in ('wallet', 'bank') else 'created',
            paid_at=timezone.now() if paid_via in ('wallet', 'bank') else None,
        )
        payment = Payment.objects.create(
            item=fresh_item,
            buyer=highest.bidder,
            amount=amount,
            purpose='order',
            status='succeeded' if paid_via in ('wallet', 'bank') else 'pending',
            provider='bank' if paid_via.startswith('bank') else 'wallet',
            provider_ref=f"ORD-{order.pk}",
            processed_at=timezone.now() if paid_via in ('wallet', 'bank') else None,
        )
        append_ledger_block({
            'type': 'order_paid' if paid_via in ('wallet', 'bank') else 'order_created',
            'item_id': fresh_item.pk,
            'buyer_id': highest.bidder.pk,
            'order_id': order.pk,
            'payment_id': payment.pk,
            'amount': str(payment.amount),
            'paid_via': paid_via,
            'transaction_id': payment.transaction_id,
            'timestamp': timezone.now().isoformat(),
        })
        fresh_item.is_settled = True
        fresh_item.is_active = False
        fresh_item.save(update_fields=['is_settled', 'is_active'])
        return True
