import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from auctions.models import (
    AuctionItem, Bid, Payment, AuctionParticipant, Order, 
    UserProfile, Wallet, WalletTransaction, WalletHold, LedgerBlock
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Restore data from backup files'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            type=str,
            help='Path to backup file to restore from'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be restored without actually restoring'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Restore specific user data only'
        )

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        dry_run = options['dry_run']
        user_id = options.get('user_id')
        
        if not os.path.exists(backup_file):
            self.stdout.write(
                self.style.ERROR(f'Backup file not found: {backup_file}')
            )
            return
        
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            if dry_run:
                self.show_restore_preview(backup_data, user_id)
            else:
                self.restore_data(backup_data, user_id)
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error reading backup file: {str(e)}')
            )

    def show_restore_preview(self, backup_data, user_id):
        """Show what would be restored without actually restoring"""
        self.stdout.write("=== RESTORE PREVIEW ===")
        
        if 'users' in backup_data:
            users = backup_data['users']
            if user_id:
                users = [u for u in users if u.get('id') == user_id]
            self.stdout.write(f"Users to restore: {len(users)}")
            for user in users[:5]:  # Show first 5
                self.stdout.write(f"  - {user.get('username')} ({user.get('email')})")
            if len(users) > 5:
                self.stdout.write(f"  ... and {len(users) - 5} more")
        
        if 'auction_items' in backup_data:
            items = backup_data['auction_items']
            self.stdout.write(f"Auction items to restore: {len(items)}")
        
        if 'bids' in backup_data:
            bids = backup_data['bids']
            self.stdout.write(f"Bids to restore: {len(bids)}")
        
        if 'payments' in backup_data:
            payments = backup_data['payments']
            self.stdout.write(f"Payments to restore: {len(payments)}")
        
        self.stdout.write("\nUse --dry-run=false to actually restore the data")

    def restore_data(self, backup_data, user_id):
        """Restore data from backup"""
        restored_count = 0
        
        with transaction.atomic():
            # Restore users
            if 'users' in backup_data:
                users = backup_data['users']
                if user_id:
                    users = [u for u in users if u.get('id') == user_id]
                
                for user_data in users:
                    user, created = User.objects.get_or_create(
                        username=user_data['username'],
                        defaults={
                            'email': user_data.get('email', ''),
                            'first_name': user_data.get('first_name', ''),
                            'last_name': user_data.get('last_name', ''),
                            'is_active': user_data.get('is_active', True),
                            'is_staff': user_data.get('is_staff', False),
                        }
                    )
                    if created:
                        restored_count += 1
                        self.stdout.write(f"Created user: {user.username}")
            
            # Restore user profiles
            if 'profiles' in backup_data:
                profiles = backup_data['profiles']
                if user_id:
                    profiles = [p for p in profiles if p.get('user') == user_id]
                
                for profile_data in profiles:
                    try:
                        user = User.objects.get(id=profile_data['user'])
                        profile, created = UserProfile.objects.get_or_create(
                            user=user,
                            defaults={
                                'phone': profile_data.get('phone', ''),
                                'location': profile_data.get('location', ''),
                                'upi_vpa': profile_data.get('upi_vpa', ''),
                                'bank_holder_name': profile_data.get('bank_holder_name', ''),
                                'bank_account_number': profile_data.get('bank_account_number', ''),
                                'bank_ifsc': profile_data.get('bank_ifsc', ''),
                                'auto_debit_consent': profile_data.get('auto_debit_consent', False),
                            }
                        )
                        if created:
                            restored_count += 1
                    except User.DoesNotExist:
                        self.stdout.write(f"User not found for profile: {profile_data.get('user')}")
            
            # Restore auction items
            if 'auction_items' in backup_data:
                items = backup_data['auction_items']
                
                for item_data in items:
                    try:
                        owner = User.objects.get(id=item_data['owner'])
                        item, created = AuctionItem.objects.get_or_create(
                            id=item_data['id'],
                            defaults={
                                'owner': owner,
                                'title': item_data['title'],
                                'description': item_data.get('description', ''),
                                'address': item_data.get('address', ''),
                                'starting_price': item_data['starting_price'],
                                'buy_now_price': item_data.get('buy_now_price'),
                                'starts_at': self.parse_datetime(item_data.get('starts_at')),
                                'ends_at': self.parse_datetime(item_data.get('ends_at')),
                                'is_active': item_data.get('is_active', True),
                                'seat_limit': item_data.get('seat_limit', 0),
                                'is_settled': item_data.get('is_settled', False),
                                'meet_url': item_data.get('meet_url', ''),
                            }
                        )
                        if created:
                            restored_count += 1
                    except User.DoesNotExist:
                        self.stdout.write(f"Owner not found for item: {item_data.get('title')}")
            
            # Restore bids
            if 'bids' in backup_data:
                bids = backup_data['bids']
                
                for bid_data in bids:
                    try:
                        item = AuctionItem.objects.get(id=bid_data['item'])
                        bidder = User.objects.get(id=bid_data['bidder'])
                        bid, created = Bid.objects.get_or_create(
                            tx_id=bid_data['tx_id'],
                            defaults={
                                'item': item,
                                'bidder': bidder,
                                'amount': bid_data['amount'],
                                'created_at': self.parse_datetime(bid_data.get('created_at')),
                                'is_active': bid_data.get('is_active', True),
                            }
                        )
                        if created:
                            restored_count += 1
                    except (AuctionItem.DoesNotExist, User.DoesNotExist):
                        self.stdout.write(f"Item or bidder not found for bid: {bid_data.get('tx_id')}")
            
            # Restore payments
            if 'payments' in backup_data:
                payments = backup_data['payments']
                
                for payment_data in payments:
                    try:
                        buyer = User.objects.get(id=payment_data['buyer']) if payment_data.get('buyer') else None
                        item = AuctionItem.objects.get(id=payment_data['item']) if payment_data.get('item') else None
                        recipient = User.objects.get(id=payment_data['recipient']) if payment_data.get('recipient') else None
                        
                        payment, created = Payment.objects.get_or_create(
                            transaction_id=payment_data['transaction_id'],
                            defaults={
                                'item': item,
                                'buyer': buyer,
                                'recipient': recipient,
                                'amount': payment_data['amount'],
                                'purpose': payment_data.get('purpose', 'order'),
                                'provider': payment_data.get('provider', 'google_pay'),
                                'provider_ref': payment_data.get('provider_ref', ''),
                                'status': payment_data.get('status', 'pending'),
                                'recipient_upi_vpa': payment_data.get('recipient_upi_vpa', ''),
                                'recipient_bank_holder_name': payment_data.get('recipient_bank_holder_name', ''),
                                'recipient_bank_account_number': payment_data.get('recipient_bank_account_number', ''),
                                'recipient_bank_ifsc': payment_data.get('recipient_bank_ifsc', ''),
                                'chain': payment_data.get('chain', ''),
                                'token_symbol': payment_data.get('token_symbol', ''),
                                'onchain_amount_wei': payment_data.get('onchain_amount_wei', ''),
                                'recipient_address': payment_data.get('recipient_address', ''),
                                'payer_address': payment_data.get('payer_address', ''),
                                'tx_hash': payment_data.get('tx_hash', ''),
                                'confirmations': payment_data.get('confirmations', 0),
                                'onchain_status': payment_data.get('onchain_status', ''),
                                'created_at': self.parse_datetime(payment_data.get('created_at')),
                                'processed_at': self.parse_datetime(payment_data.get('processed_at')),
                            }
                        )
                        if created:
                            restored_count += 1
                    except User.DoesNotExist:
                        self.stdout.write(f"User not found for payment: {payment_data.get('transaction_id')}")
                    except AuctionItem.DoesNotExist:
                        self.stdout.write(f"Item not found for payment: {payment_data.get('transaction_id')}")
        
        self.stdout.write(
            self.style.SUCCESS(f'Data restoration completed. {restored_count} records restored.')
        )

    def parse_datetime(self, datetime_str):
        """Parse datetime string from backup"""
        if not datetime_str:
            return None
        try:
            from django.utils.dateparse import parse_datetime
            return parse_datetime(datetime_str)
        except:
            return None