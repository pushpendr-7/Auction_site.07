from django import forms
from .models import Bid, BankAccount


class RechargeForm(forms.Form):
    amount = forms.DecimalField(min_value=1, max_digits=12, decimal_places=2)
    method = forms.ChoiceField(choices=[
        ('gpay', 'Google Pay / UPI'),
        ('bank', 'Bank Transfer'),
        ('crypto', 'Crypto'),
    ])


class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = ['amount']


class BankLinkForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['bank_name', 'account_number', 'ifsc', 'deposit_instructions']
