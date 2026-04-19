from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
import hashlib
import json
from .models import (
    AuctionItem, Bid, Payment, AuctionParticipant, Order, 
    UserProfile, Wallet, WalletTransaction, WalletHold, LedgerBlock, Transaction
)
import secrets
import string
from cryptography.fernet import Fernet
import base64
import os


def append_ledger_block(data):
    """Append a new block to the ledger with the given data."""
    # Get the last block to calculate the hash
    last_block = LedgerBlock.objects.order_by('-index').first()
    
    if last_block:
        index = last_block.index + 1
        previous_hash = last_block.hash
    else:
        index = 0
        previous_hash = "0"
    
    # Create the block data
    block_data = {
        'index': index,
        'timestamp': timezone.now().isoformat(),
        'previous_hash': previous_hash,
        'data': data,
        'nonce': 0
    }
    
    # Simple proof of work (find a hash starting with "0000")
    while True:
        block_string = json.dumps(block_data, sort_keys=True)
        block_hash = hashlib.sha256(block_string.encode()).hexdigest()
        if block_hash.startswith("0000"):
            break
        block_data['nonce'] += 1
    
    # Create and save the block
    block = LedgerBlock.objects.create(
        index=index,
        previous_hash=previous_hash,
        data=data,
        nonce=block_data['nonce'],
        hash=block_hash
    )
    
    return block


def get_available_balance(user):
    """Get available wallet balance excluding holds."""
    wallet = get_or_create_wallet(user)
    total_holds = sum(
        hold.amount for hold in WalletHold.objects.filter(
            user=user, status='active'
        )
    )
    return wallet.balance - total_holds


def get_or_create_wallet(user):
    """Get or create wallet for user."""
    wallet, created = Wallet.objects.get_or_create(user=user)
    return wallet


def apply_payment_effects(payment):
    """Apply the effects of a successful payment."""
    if payment.processed_at:
        return  # Already processed
    
    with transaction.atomic():
        if payment.purpose == 'recharge':
            # Add funds to wallet
            wallet = get_or_create_wallet(payment.buyer)
            wallet.balance += payment.amount
            wallet.save(update_fields=['balance'])
            
            WalletTransaction.objects.create(
                user=payment.buyer,
                payment=payment,
                kind='credit',
                amount=payment.amount,
                balance_after=wallet.balance,
            )
            Transaction.objects.create(
                user=payment.buyer,
                payment=payment,
                tx_type='RECHARGE',
                status='SUCCESS',
                amount=payment.amount,
                metadata={'provider': payment.provider, 'provider_ref': payment.provider_ref},
            )
        
        elif payment.purpose == 'seat':
            # Book seat for auction
            participant = AuctionParticipant.objects.filter(
                item=payment.item, user=payment.buyer
            ).first()
            if participant:
                participant.is_booked = True
                participant.paid = True
                participant.paid_at = timezone.now()
                participant.booking_code = _generate_booking_code()
                participant.save(update_fields=['is_booked', 'paid', 'paid_at', 'booking_code'])
            Transaction.objects.create(
                user=payment.buyer,
                item=payment.item,
                payment=payment,
                tx_type='PAYMENT',
                status='SUCCESS',
                amount=payment.amount,
                metadata={'purpose': 'seat'},
            )
        
        elif payment.purpose == 'penalty':
            # Clear penalty
            participant = AuctionParticipant.objects.filter(
                item=payment.item, user=payment.buyer
            ).first()
            if participant:
                participant.penalty_due = False
                participant.save(update_fields=['penalty_due'])
            Transaction.objects.create(
                user=payment.buyer,
                item=payment.item,
                payment=payment,
                tx_type='PAYMENT',
                status='SUCCESS',
                amount=payment.amount,
                metadata={'purpose': 'penalty'},
            )
        
        elif payment.purpose in ('order', 'buy_now'):
            # Create order
            created_order = Order.objects.create(
                item=payment.item,
                buyer=payment.buyer,
                amount=payment.amount,
                status='paid',
                paid_at=timezone.now(),
            )
            Transaction.objects.create(
                user=payment.buyer,
                item=payment.item,
                payment=payment,
                tx_type='PAYMENT',
                status='SUCCESS',
                amount=payment.amount,
                metadata={'purpose': payment.purpose, 'order_id': created_order.pk},
            )
        
        # Mark payment as processed
        payment.processed_at = timezone.now()
        payment.save(update_fields=['processed_at'])


def settle_auction_item(item):
    """Settle an auction item and create order for winner."""
    if item.is_settled:
        return False
    
    # Lock item row to avoid concurrent settlements
    item = AuctionItem.objects.select_for_update().get(pk=item.pk)
    highest_bid = item.bids.filter(is_active=True).order_by('-amount', 'created_at').first()
    if not highest_bid:
        return False
    
    with transaction.atomic():
        # Create order for winner
        order = Order.objects.create(
            item=item,
            buyer=highest_bid.bidder,
            amount=highest_bid.amount,
            status='paid',
            paid_at=timezone.now(),
        )
        
        # Consume the hold amount
        # Lock hold row if exists
        hold = WalletHold.objects.select_for_update().filter(
            item=item, user=highest_bid.bidder, status='active'
        ).first()
        if hold:
            hold.status = 'consumed'
            hold.save(update_fields=['status', 'updated_at'])
            
            # Deduct from wallet (lock row)
            wallet = get_or_create_wallet(highest_bid.bidder)
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance -= hold.amount
            wallet.save(update_fields=['balance'])
            
            WalletTransaction.objects.create(
                user=highest_bid.bidder,
                item=item,
                kind='hold_consume',
                amount=hold.amount,
                balance_after=wallet.balance,
            )
            Transaction.objects.create(
                user=highest_bid.bidder,
                item=item,
                tx_type='PAYMENT',
                status='SUCCESS',
                amount=hold.amount,
                metadata={'settlement': True, 'bid_id': highest_bid.pk},
            )
        
        # Mark item as settled
        item.is_settled = True
        item.is_active = False
        item.save(update_fields=['is_settled', 'is_active'])
        
        # Release all other holds
        WalletHold.objects.filter(
            item=item, status='active'
        ).exclude(user=highest_bid.bidder).update(
            status='released',
            updated_at=timezone.now()
        )
        
        # Add ledger block
        append_ledger_block({
            'type': 'auction_settled',
            'item_id': item.pk,
            'winner_id': highest_bid.bidder.pk,
            'winning_amount': str(highest_bid.amount),
            'order_id': order.pk,
            'timestamp': timezone.now().isoformat(),
        })
    
    return True


def _generate_booking_code(length=8):
    """Generate a unique booking code."""
    chars = string.ascii_uppercase.replace('O', '').replace('I', '').replace('L', '') + \
            string.digits.replace('0', '').replace('1', '')
    return ''.join(secrets.choices(chars, k=length))


class DataEncryption:
    """Utility class for encrypting sensitive user data"""
    
    @staticmethod
    def get_encryption_key():
        """Get or create encryption key"""
        key = getattr(settings, 'DATA_ENCRYPTION_KEY', None)
        if not key:
            # Generate a new key if none exists
            key = Fernet.generate_key()
            # In production, store this securely
            print(f"WARNING: Generated new encryption key. Store this securely: {key.decode()}")
        return key
    
    @staticmethod
    def encrypt_data(data):
        """Encrypt sensitive data"""
        if not data:
            return data
        
        key = DataEncryption.get_encryption_key()
        f = Fernet(key)
        
        if isinstance(data, str):
            return f.encrypt(data.encode()).decode()
        elif isinstance(data, dict):
            # Encrypt string values in dictionary
            encrypted_data = {}
            for k, v in data.items():
                if isinstance(v, str) and v:
                    encrypted_data[k] = f.encrypt(v.encode()).decode()
                else:
                    encrypted_data[k] = v
            return encrypted_data
        else:
            return data
    
    @staticmethod
    def decrypt_data(encrypted_data):
        """Decrypt sensitive data"""
        if not encrypted_data:
            return encrypted_data
        
        key = DataEncryption.get_encryption_key()
        f = Fernet(key)
        
        try:
            if isinstance(encrypted_data, str):
                return f.decrypt(encrypted_data.encode()).decode()
            elif isinstance(encrypted_data, dict):
                # Decrypt string values in dictionary
                decrypted_data = {}
                for k, v in encrypted_data.items():
                    if isinstance(v, str) and v:
                        try:
                            decrypted_data[k] = f.decrypt(v.encode()).decode()
                        except:
                            decrypted_data[k] = v  # Return original if decryption fails
                    else:
                        decrypted_data[k] = v
                return decrypted_data
            else:
                return encrypted_data
        except Exception:
            # Return original data if decryption fails
            return encrypted_data


def encrypt_sensitive_user_data(user_data):
    """Encrypt sensitive fields in user data"""
    sensitive_fields = [
        'email', 'phone', 'bank_account_number', 'upi_vpa',
        'bank_holder_name', 'bank_ifsc'
    ]
    
    if isinstance(user_data, dict):
        for field in sensitive_fields:
            if field in user_data and user_data[field]:
                user_data[field] = DataEncryption.encrypt_data(user_data[field])
    
    return user_data


def create_permanent_data_archive(user_data, archive_path):
    """Create a permanent archive of user data with encryption"""
    # Encrypt sensitive data
    encrypted_data = encrypt_sensitive_user_data(user_data)
    
    # Add metadata
    archive_data = {
        'archive_created': timezone.now().isoformat(),
        'data_encrypted': True,
        'encryption_method': 'Fernet',
        'user_data': encrypted_data,
    }
    
    # Save to file
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(archive_data, f, indent=2, default=str)
    
    return archive_path


def verify_data_integrity(data):
    """Verify data integrity using checksums"""
    data_string = json.dumps(data, sort_keys=True, default=str)
    checksum = hashlib.sha256(data_string.encode()).hexdigest()
    return checksum


def create_data_backup_with_verification(data, backup_path):
    """Create backup with integrity verification"""
    # Create backup
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)
    
    # Calculate and store checksum
    checksum = verify_data_integrity(data)
    checksum_path = backup_path + '.checksum'
    with open(checksum_path, 'w') as f:
        f.write(checksum)
    
    return backup_path, checksum