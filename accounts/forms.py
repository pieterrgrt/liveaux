from allauth.account.forms import ResetPasswordForm as AllauthResetPasswordForm
from django import forms
from django.conf import settings

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "log_is_public", "library_is_public"]
        labels = {"display_name": "Name"}
        help_texts = {"display_name": "Shown to people you manage pages with, and on your log, library and lists if you make them public."}


class DeleteAccountForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, help_text="To make sure it's really you.")
    confirm = forms.BooleanField(label="I understand this deletes my account and my log for good.")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("That's not your password.")
        return password


class ResetPasswordForm(AllauthResetPasswordForm):
    """Without a mail server a reset link can't arrive, so say so instead of pretending it was sent."""

    def clean_email(self):
        if not settings.EMAIL_CAN_SEND:
            raise forms.ValidationError(
                "liveaux can't send email yet, so a reset link wouldn't arrive. "
                f"Write to {settings.CONTACT_EMAIL} and we'll help you back in."
            )
        return super().clean_email()
