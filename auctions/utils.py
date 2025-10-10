import hashlib
from typing import Dict, Any
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from .models import LedgerBlock, Wallet, WalletHold


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
    return (wallet.balance or Decimal('0')) - holds_total
