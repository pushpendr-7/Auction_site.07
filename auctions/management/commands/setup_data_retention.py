from django.core.management.base import BaseCommand
from auctions.models import DataRetentionPolicy


class Command(BaseCommand):
    help = 'Setup data retention policies for permanent data storage'

    def handle(self, *args, **options):
        # Define retention policies for different data types
        policies = [
            {
                'data_type': 'user_profiles',
                'retention_days': 2555,  # 7 years
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'auction_items',
                'retention_days': 1825,  # 5 years
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'bids',
                'retention_days': 1825,  # 5 years
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'payments',
                'retention_days': 2555,  # 7 years (financial data)
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'orders',
                'retention_days': 1825,  # 5 years
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'wallet_transactions',
                'retention_days': 2555,  # 7 years (financial data)
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'ledger_blocks',
                'retention_days': 3650,  # 10 years (blockchain data)
                'auto_delete': False,
                'backup_before_delete': True,
            },
            {
                'data_type': 'auction_participants',
                'retention_days': 1095,  # 3 years
                'auto_delete': False,
                'backup_before_delete': True,
            },
        ]

        created_count = 0
        updated_count = 0

        for policy_data in policies:
            policy, created = DataRetentionPolicy.objects.get_or_create(
                data_type=policy_data['data_type'],
                defaults=policy_data
            )
            
            if not created:
                # Update existing policy
                for key, value in policy_data.items():
                    setattr(policy, key, value)
                policy.save()
                updated_count += 1
            else:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Data retention policies setup completed. '
                f'Created: {created_count}, Updated: {updated_count}'
            )
        )