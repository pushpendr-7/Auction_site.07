import json
import os
import zipfile
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from django.contrib.auth import get_user_model
from auctions.models import (
    AuctionItem, Bid, Payment, AuctionParticipant, Order, 
    UserProfile, Wallet, WalletTransaction, WalletHold, LedgerBlock
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Create comprehensive backup of all user data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default='/tmp/auction_backups',
            help='Directory to save backup files'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Backup specific user data only'
        )
        parser.add_argument(
            '--format',
            type=str,
            choices=['json', 'csv', 'sql'],
            default='json',
            help='Backup format'
        )

    def handle(self, *args, **options):
        output_dir = options['output_dir']
        user_id = options.get('user_id')
        backup_format = options['format']
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if user_id:
            self.backup_user_data(user_id, output_dir, timestamp, backup_format)
        else:
            self.backup_all_data(output_dir, timestamp, backup_format)
        
        self.stdout.write(
            self.style.SUCCESS(f'Backup completed successfully in {output_dir}')
        )

    def backup_user_data(self, user_id, output_dir, timestamp, backup_format):
        """Backup data for a specific user"""
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User with ID {user_id} not found')
            )
            return

        user_data = self.get_user_complete_data(user)
        
        if backup_format == 'json':
            filename = f'user_{user_id}_backup_{timestamp}.json'
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, indent=2, default=str)
        
        self.stdout.write(f'User {user.username} data backed up to {filename}')

    def backup_all_data(self, output_dir, timestamp, backup_format):
        """Backup all system data"""
        all_data = self.get_all_system_data()
        
        if backup_format == 'json':
            filename = f'complete_system_backup_{timestamp}.json'
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, indent=2, default=str)
        
        # Create compressed backup
        zip_filename = f'complete_system_backup_{timestamp}.zip'
        zip_path = os.path.join(output_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(filepath, os.path.basename(filepath))
            
            # Add media files if they exist
            media_dir = settings.MEDIA_ROOT
            if os.path.exists(media_dir):
                for root, dirs, files in os.walk(media_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, media_dir)
                        zipf.write(file_path, f'media/{arcname}')
        
        self.stdout.write(f'Complete system backup created: {zip_filename}')

    def get_user_complete_data(self, user):
        """Get all data related to a specific user"""
        return {
            'user_info': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'date_joined': user.date_joined,
                'last_login': user.last_login,
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

    def get_all_system_data(self):
        """Get all system data"""
        return {
            'backup_timestamp': datetime.now().isoformat(),
            'users': self.serialize_model_data(User.objects.all()),
            'profiles': self.serialize_model_data(UserProfile.objects.all()),
            'wallets': self.serialize_model_data(Wallet.objects.all()),
            'wallet_transactions': self.serialize_model_data(WalletTransaction.objects.all()),
            'wallet_holds': self.serialize_model_data(WalletHold.objects.all()),
            'auction_items': self.serialize_model_data(AuctionItem.objects.all()),
            'bids': self.serialize_model_data(Bid.objects.all()),
            'payments': self.serialize_model_data(Payment.objects.all()),
            'orders': self.serialize_model_data(Order.objects.all()),
            'auction_participants': self.serialize_model_data(AuctionParticipant.objects.all()),
            'ledger_blocks': self.serialize_model_data(LedgerBlock.objects.all()),
        }

    def serialize_model_data(self, queryset):
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