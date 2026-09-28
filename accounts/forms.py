from django import forms

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name"]
        labels = {"display_name": "Name"}
        help_texts = {"display_name": "Shown to people you manage pages with."}
