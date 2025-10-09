from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from django.conf import settings
from web3 import Web3


@dataclass
class Quote:
    token_symbol: str
    fiat_amount_inr: Decimal
    token_amount: Decimal
    wei_amount: int


def get_web3() -> Web3:
    rpc_url = getattr(settings, 'BLOCKCHAIN_RPC_URL', '')
    if not rpc_url:
        raise RuntimeError('BLOCKCHAIN_RPC_URL not configured')
    return Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))


def inr_to_token_quote(inr_amount: Decimal) -> Quote:
    token_symbol = getattr(settings, 'BLOCKCHAIN_CURRENCY', 'MATIC')
    price_per_token = Decimal(str(getattr(settings, 'BLOCKCHAIN_PRICE_INR_PER_TOKEN', '100.0')))
    if price_per_token <= 0:
        raise ValueError('Invalid BLOCKCHAIN_PRICE_INR_PER_TOKEN')
    token_amount = (inr_amount / price_per_token).quantize(Decimal('0.000000000000000001'))
    wei_amount = int(token_amount * Decimal(10**18))
    return Quote(token_symbol=token_symbol, fiat_amount_inr=inr_amount, token_amount=token_amount, wei_amount=wei_amount)


def checksum_address(address: str) -> str:
    w3 = get_web3()
    if not w3.is_address(address):
        raise ValueError('Invalid address')
    return w3.to_checksum_address(address)


def get_tx_receipt(tx_hash: str) -> Optional[Dict[str, Any]]:
    w3 = get_web3()
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        return None
    if receipt is None:
        return None
    return dict(receipt)


def get_confirmations(tx_block_number: Optional[int]) -> int:
    if tx_block_number is None:
        return 0
    w3 = get_web3()
    latest = w3.eth.block_number
    return max(0, int(latest) - int(tx_block_number))


def validate_native_transfer(tx_hash: str, expected_to: str, expected_wei: int) -> Dict[str, Any]:
    w3 = get_web3()
    receipt = get_tx_receipt(tx_hash)
    if not receipt:
        return {"ok": False, "reason": "no_receipt"}
    status_ok = int(receipt.get('status', 0)) == 1
    tx = w3.eth.get_transaction(tx_hash)
    to_addr = tx.get('to')
    value = int(tx.get('value', 0))
    # Normalize addresses to checksum for compare
    try:
        expected_to_cs = w3.to_checksum_address(expected_to)
        to_addr_cs = w3.to_checksum_address(to_addr) if to_addr else None
    except Exception:
        return {"ok": False, "reason": "invalid_address"}
    amount_ok = value >= int(expected_wei)
    to_ok = (to_addr_cs == expected_to_cs)
    confirmations = get_confirmations(receipt.get('blockNumber'))
    min_conf = int(getattr(settings, 'BLOCKCHAIN_MIN_CONFIRMATIONS', 3))
    confirmed = confirmations >= min_conf
    return {
        "ok": bool(status_ok and amount_ok and to_ok),
        "status_ok": status_ok,
        "amount_ok": amount_ok,
        "to_ok": to_ok,
        "confirmations": confirmations,
        "confirmed": confirmed,
        "receipt": receipt,
        "value": value,
        "to": to_addr,
        "min_confirmations": min_conf,
    }
