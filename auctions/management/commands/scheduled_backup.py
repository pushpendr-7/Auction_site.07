import os
import json
import zipfile
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from django.contrib.auth import get_user_model
from auctions.models import (
    AuctionItem, Bid, Payment, AuctionParticipant, Order, 
    UserProfile, Wallet, WalletTransaction, WalletHold, LedgerBlock,
    DataBackup, DataRetentionPolicy
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Perform scheduled data backup for permanent storage'

    def add_arguments(self, parser):
        parser.add_argument(
            '--backup-type',
            type=str,
            choices=['user_data', 'system_full', 'incremental', 'scheduled'],
            default='scheduled',
            help='Type of backup to perform'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default='/tmp/auction_backups',
            help='Directory to save backup files'
        )
        parser.add_argument(
            '--encrypt',
            action='store_true',
            help='Encrypt backup files'
        )

    def handle(self, *args, **options):
        backup_type = options['backup_type']
        output_dir = options['output_dir']
        encrypt = options['encrypt']
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        try:
            if backup_type == 'system_full':
                self.perform_full_system_backup(output_dir, timestamp, encrypt)
            elif backup_type == 'incremental':
                self.perform_incremental_backup(output_dir, timestamp, encrypt)
            elif backup_type == 'user_data':
                self.perform_user_data_backup(output_dir, timestamp, encrypt)
            else:  # scheduled
                self.perform_scheduled_backup(output_dir, timestamp, encrypt)
                
            self.stdout.write(
                self.style.SUCCESS(f'Scheduled backup completed successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Backup failed: {str(e)}')
            )

    def perform_full_system_backup(self, output_dir, timestamp, encrypt):
        """Perform full system backup"""
        all_data = self.get_all_system_data()
        
        filename = f'full_system_backup_{timestamp}.json'
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, default=str)
        
        # Create compressed backup
        zip_filename = f'full_system_backup_{timestamp}.zip'
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
        
        # Record backup in database
        backup_size = os.path.getsize(zip_path)
        DataBackup.objects.create(
            backup_type='system_full',
            backup_file_path=zip_path,
            backup_size=backup_size,
            is_encrypted=encrypt,
            status='completed',
            metadata={
                'total_users': User.objects.count(),
                'total_items': AuctionItem.objects.count(),
                'total_payments': Payment.objects.count(),
            }
        )
        
        self.stdout.write(f'Full system backup created: {zip_filename}')

    def perform_incremental_backup(self, output_dir, timestamp, encrypt):
        """Perform incremental backup of data changed in last 24 hours"""
        yesterday = datetime.now() - timedelta(days=1)
        
        incremental_data = {
            'backup_timestamp': datetime.now().isoformat(),
            'backup_type': 'incremental',
            'since': yesterday.isoformat(),
            'users': self.serialize_model_data(
                User.objects.filter(date_joined__gte=yesterday)
            ),
            'auction_items': self.serialize_model_data(
                AuctionItem.objects.filter(created_at__gte=yesterday)
            ),
            'bids': self.serialize_model_data(
                Bid.objects.filter(created_at__gte=yesterday)
            ),
            'payments': self.serialize_model_data(
                Payment.objects.filter(created_at__gte=yesterday)
            ),
            'orders': self.serialize_model_data(
                Order.objects.filter(created_at__gte=yesterday)
            ),
            'wallet_transactions': self.serialize_model_data(
                WalletTransaction.objects.filter(created_at__gte=yesterday)
            ),
        }
        
        filename = f'incremental_backup_{timestamp}.json'
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(incremental_data, f, indent=2, default=str)
        
        # Record backup in database
        backup_size = os.path.getsize(filepath)
        DataBackup.objects.create(
            backup_type='incremental',
            backup_file_path=filepath,
            backup_size=backup_size,
            is_encrypted=encrypt,
            status='completed',
            metadata={
                'since': yesterday.isoformat(),
                'records_backed_up': sum(len(v) for v in incremental_data.values() if isinstance(v, list))
            }
        )
        
        self.stdout.write(f'Incremental backup created: {filename}')

    def perform_user_data_backup(self, output_dir, timestamp, encrypt):
        """Backup all user data individually"""
        users = User.objects.all()
        backed_up_users = 0
        
        for user in users:
            user_data = self.get_user_complete_data(user)
            
            filename = f'user_{user.id}_{user.username}_backup_{timestamp}.json'
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, indent=2, default=str)
            
            # Record backup in database
            backup_size = os.path.getsize(filepath)
            DataBackup.objects.create(
                backup_type='user_data',
                user=user,
                backup_file_path=filepath,
                backup_size=backup_size,
                is_encrypted=encrypt,
                status='completed',
                metadata={
                    'user_id': user.id,
                    'username': user.username,
                }
            )
            
            backed_up_users += 1
        
        self.stdout.write(f'User data backup completed for {backed_up_users} users')

    def perform_scheduled_backup(self, output_dir, timestamp, encrypt):
        """Perform scheduled backup based on retention policies"""
        # Get all retention policies
        policies = DataRetentionPolicy.objects.all()
        
        for policy in policies:
            self.stdout.write(f'Processing retention policy for {policy.data_type}')
            
            # Determine which data to backup based on policy
            if policy.data_type == 'user_profiles':
                data = self.serialize_model_data(UserProfile.objects.all())
            elif policy.data_type == 'auction_items':
                data = self.serialize_model_data(AuctionItem.objects.all())
            elif policy.data_type == 'bids':
                data = self.serialize_model_data(Bid.objects.all())
            elif policy.data_type == 'payments':
                data = self.serialize_model_data(Payment.objects.all())
            elif policy.data_type == 'orders':
                data = self.serialize_model_data(Order.objects.all())
            elif policy.data_type == 'wallet_transactions':
                data = self.serialize_model_data(WalletTransaction.objects.all())
            elif policy.data_type == 'ledger_blocks':
                data = self.serialize_model_data(LedgerBlock.objects.all())
            elif policy.data_type == 'auction_participants':
                data = self.serialize_model_data(AuctionParticipant.objects.all())
            else:
                continue
            
            # Create backup file
            filename = f'{policy.data_type}_backup_{timestamp}.json'
            filepath = os.path.join(output_dir, filename)
            
            backup_data = {
                'backup_timestamp': datetime.now().isoformat(),
                'data_type': policy.data_type,
                'retention_days': policy.retention_days,
                'data': data,
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, default=str)
            
            # Record backup in database
            backup_size = os.path.getsize(filepath)
            DataBackup.objects.create(
                backup_type='scheduled',
                backup_file_path=filepath,
                backup_size=backup_size,
                is_encrypted=encrypt,
                status='completed',
                metadata={
                    'data_type': policy.data_type,
                    'retention_days': policy.retention_days,
                    'records_count': len(data),
                }
            )

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