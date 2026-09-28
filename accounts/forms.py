from django import forms

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "log_is_public"]
        labels = {"display_name": "Name"}
        help_texts = {"display_name": "Shown to people you manage pages with, and on your log if you make it public."}


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
