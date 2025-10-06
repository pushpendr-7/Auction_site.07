import hashlib
from typing import Dict, Any
import random
import string
from django.db import transaction
from .models import LedgerBlock


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


def generate_booking_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))
