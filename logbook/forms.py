from django import forms

from .models import LogEntry


class LogEntryForm(forms.ModelForm):
    class Meta:
        model = LogEntry
        fields = ["rating", "note"]
        labels = {"rating": "Your rating", "note": "Note"}
        widgets = {"note": forms.Textarea(attrs={"rows": 3, "maxlength": 280})}
        help_texts = {"note": "A few words to remember it by. Max 280 characters."}
