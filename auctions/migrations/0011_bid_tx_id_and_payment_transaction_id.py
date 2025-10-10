from django.db import migrations, models
import uuid


def populate_tx_ids(apps, schema_editor):
    Bid = apps.get_model('auctions', 'Bid')
    Payment = apps.get_model('auctions', 'Payment')
    # Populate Bid.tx_id
    for bid in Bid.objects.filter(tx_id__isnull=True):
        bid.tx_id = str(uuid.uuid4())
        bid.save(update_fields=['tx_id'])
    for bid in Bid.objects.filter(tx_id=''):
        bid.tx_id = str(uuid.uuid4())
        bid.save(update_fields=['tx_id'])
    # Populate Payment.transaction_id
    for pay in Payment.objects.filter(transaction_id__isnull=True):
        pay.transaction_id = str(uuid.uuid4())
        pay.save(update_fields=['transaction_id'])
    for pay in Payment.objects.filter(transaction_id=''):
        pay.transaction_id = str(uuid.uuid4())
        pay.save(update_fields=['transaction_id'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('auctions', '0010_payment_recipient_and_bank_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='bid',
            name='tx_id',
            field=models.CharField(max_length=36, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='transaction_id',
            field=models.CharField(max_length=36, null=True, blank=True),
        ),
        migrations.RunPython(populate_tx_ids, reverse_code=noop),
        migrations.AlterField(
            model_name='bid',
            name='tx_id',
            field=models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False),
        ),
        migrations.AlterField(
            model_name='payment',
            name='transaction_id',
            field=models.CharField(max_length=36, unique=True, default=uuid.uuid4, editable=False),
        ),
    ]
