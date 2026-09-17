from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from auctions.models import AuctionItem, AuctionParticipant, Bid, UserProfile


class Command(BaseCommand):
    help = 'Create safe, repeatable demo auction data for development previews.'

    def handle(self, *args, **options):
        User = get_user_model()
        seller, _ = User.objects.get_or_create(
            username='demo_seller',
            defaults={
                'first_name': 'Demo',
                'last_name': 'Seller',
                'email': 'demo-seller@example.invalid',
            },
        )
        seller.set_unusable_password()
        seller.save(update_fields=['password', 'first_name', 'last_name', 'email'])
        UserProfile.objects.get_or_create(
            user=seller,
            defaults={'location': 'New Delhi', 'phone': '+91 90000 00001'},
        )

        bidder_names = ('demo_buyer', 'demo_collector')
        bidders = []
        for index, username in enumerate(bidder_names, start=2):
            bidder, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': 'Demo',
                    'last_name': 'Buyer' if index == 2 else 'Collector',
                    'email': f'{username}@example.invalid',
                },
            )
            bidder.set_unusable_password()
            bidder.save(update_fields=['password'])
            UserProfile.objects.get_or_create(
                user=bidder,
                defaults={'location': 'Mumbai' if index == 2 else 'Jaipur'},
            )
            bidders.append(bidder)

        now = timezone.now()
        items = [
            {
                'title': 'Vintage Film Camera',
                'description': 'Well-kept 35mm camera for collectors and photography lovers.',
                'city': 'New Delhi',
                'starting': '4500.00',
                'buy_now': '12000.00',
                'ends': now + timezone.timedelta(days=3),
            },
            {
                'title': 'Handmade Blue Pottery Set',
                'description': 'Decorative Jaipur blue pottery set with three matching pieces.',
                'city': 'Jaipur',
                'starting': '1800.00',
                'buy_now': '5500.00',
                'ends': now + timezone.timedelta(days=5),
            },
            {
                'title': 'Refurbished Gaming Laptop',
                'description': 'Performance laptop suitable for study, design and gaming.',
                'city': 'Bengaluru',
                'starting': '25000.00',
                'buy_now': '42000.00',
                'ends': now + timezone.timedelta(days=2),
            },
            {
                'title': 'Solid Wood Study Table',
                'description': 'Sturdy reclaimed-wood table with a clean, minimal finish.',
                'city': 'Pune',
                'starting': '6500.00',
                'buy_now': '15000.00',
                'ends': now + timezone.timedelta(days=7),
            },
            {
                'title': 'Limited Edition Art Print',
                'description': 'Numbered archival art print, supplied with a protective sleeve.',
                'city': 'Mumbai',
                'starting': '900.00',
                'buy_now': '2800.00',
                'ends': now + timezone.timedelta(days=4),
            },
            {
                'title': 'Classic Road Bicycle',
                'description': 'Serviced steel-frame bicycle for city rides and weekend trips.',
                'city': 'Hyderabad',
                'starting': '8000.00',
                'buy_now': '18500.00',
                'ends': now + timezone.timedelta(days=6),
            },
        ]

        created = 0
        for index, item_data in enumerate(items):
            item, was_created = AuctionItem.objects.get_or_create(
                owner=seller,
                title=item_data['title'],
                defaults={
                    'description': item_data['description'],
                    'address': f'Demo pickup address {index + 1}',
                    'pickup_city': item_data['city'],
                    'pickup_pincode': '110001',
                    'delivery_mode': 'both',
                    'delivery_charges': Decimal('99.00'),
                    'starting_price': Decimal(item_data['starting']),
                    'buy_now_price': Decimal(item_data['buy_now']),
                    'starts_at': now - timezone.timedelta(hours=2),
                    'ends_at': item_data['ends'],
                    'is_active': True,
                    'seat_limit': 50,
                },
            )
            created += int(was_created)
            for bidder in bidders:
                AuctionParticipant.objects.get_or_create(item=item, user=bidder)

            if item.title == 'Vintage Film Camera':
                Bid.objects.get_or_create(
                    item=item,
                    bidder=bidders[0],
                    defaults={
                        'amount': Decimal('5200.00'),
                        'is_active': True,
                    },
                )
                Bid.objects.get_or_create(
                    item=item,
                    bidder=bidders[1],
                    defaults={
                        'amount': Decimal('6100.00'),
                        'is_active': True,
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            f'Demo data ready: {len(items)} auctions ({created} newly created).'
        ))