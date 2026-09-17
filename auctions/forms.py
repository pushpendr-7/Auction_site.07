from django import forms
from django.contrib.auth import get_user_model
from .models import Bid, BankAccount

User = get_user_model()


class RechargeForm(forms.Form):
    amount = forms.DecimalField(min_value=1, max_digits=12, decimal_places=2)
    method = forms.ChoiceField(choices=[
        ('gpay', 'Google Pay'),
        ('phonepe', 'PhonePe'),
    ])


class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = ['amount']


class BankLinkForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['bank_name', 'account_number', 'ifsc', 'deposit_instructions']


class ProfileForm(forms.Form):
    first_name = forms.CharField(
        max_length=150,
        required=False,
        label='First name',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Last name',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        label='Phone',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    location = forms.CharField(
        max_length=120,
        required=False,
        label='City / location',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        profile = getattr(user, 'profile', None)
        if not self.is_bound:
            self.initial.update({
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'phone': profile.phone if profile else '',
                'location': profile.location if profile else '',
            })

    def save(self):
        from .models import UserProfile

        self.user.first_name = self.cleaned_data['first_name'].strip()
        self.user.last_name = self.cleaned_data['last_name'].strip()
        self.user.email = self.cleaned_data['email'].strip()
        self.user.save(update_fields=['first_name', 'last_name', 'email'])
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.phone = self.cleaned_data['phone'].strip()
        profile.location = self.cleaned_data['location'].strip()
        profile.save(update_fields=['phone', 'location'])
        return self.user
