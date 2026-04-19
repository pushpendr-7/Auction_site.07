from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from auctions.models import AuctionItem
from auctions.utils import settle_auction_item


class Command(BaseCommand):
    help = "Settle ended auctions and charge winners automatically"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not persist changes; log only')
        parser.add_argument('--limit', type=int, default=100, help='Max items to process')

    def handle(self, *args, **options):
        dry = options['dry_run']
        limit = options['limit']
        now = timezone.now()
        qs = AuctionItem.objects.filter(is_active=True, is_settled=False, ends_at__lte=now).order_by('ends_at')[:limit]
        processed = 0
        for item in qs:
            if dry:
                self.stdout.write(self.style.WARNING(f"[dry-run] Would settle item {item.pk}"))
                continue
            try:
                ok = settle_auction_item(item)
                if ok:
                    processed += 1
                    self.stdout.write(self.style.SUCCESS(f"Settled item {item.pk}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Skipped item {item.pk} (not eligible or already settled)"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error settling item {item.pk}: {e}"))
        self.stdout.write(self.style.SUCCESS(f"Done. Settled {processed} auctions."))
