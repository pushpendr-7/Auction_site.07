from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from .models import AuctionItem, Bid, Wallet, WalletHold
from .utils import get_or_create_wallet, get_available_balance


class WalletAndBiddingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='alice', password='pass')
        self.seller = User.objects.create_user(username='bob', password='pass')
        self.item = AuctionItem.objects.create(
            owner=self.seller,
            title='Test Item',
            description='Desc',
            image='items/x.png',
            address='Addr',
            starting_price=Decimal('100.00'),
            starts_at=timezone.now() - timezone.timedelta(hours=1),
            ends_at=timezone.now() + timezone.timedelta(hours=1),
        )

    def test_wallet_available_balance_with_hold(self):
        wallet = get_or_create_wallet(self.user)
        wallet.balance = Decimal('500.00')
        wallet.save()
        self.assertEqual(get_available_balance(self.user), Decimal('500.00'))
        # create hold of 200
        WalletHold.objects.create(user=self.user, item=self.item, amount=Decimal('200.00'))
        self.assertEqual(get_available_balance(self.user), Decimal('300.00'))

    def test_bid_tx_id_generated(self):
        bid = Bid.objects.create(item=self.item, bidder=self.user, amount=Decimal('150.00'), is_active=True)
        self.assertTrue(bid.tx_id)
        self.assertEqual(len(str(bid.tx_id)), 36)

# Create your tests here.
