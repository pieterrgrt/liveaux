from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Copy, Entry, Item, MediaList, MediaType, Status


class EntryForm(forms.ModelForm):
    class Meta:
        model = Entry
        fields = ["status", "score", "progress", "started_on", "finished_on", "repeats", "notes"]
        labels = {"score": "Your score", "started_on": "Started", "finished_on": "Finished"}
        widgets = {
            "started_on": forms.DateInput(attrs={"type": "date"}),
            "finished_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {"notes": "Only you can see these, unless your library is public."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        item = self.instance.item
        unit = item.info["unit"]
        self.fields["progress"].label = f"{unit.capitalize()}s" if unit != "film" else "Progress"
        self.fields["progress"].help_text = f"Of {item.total}." if item.total else ""
        if item.behaviour == "sessions":
            self.fields["progress"].label = f"{unit.capitalize()}s"
        if item.has_episodes:
            # Progress of a series follows the episodes you check in.
            del self.fields["progress"]

    def clean(self):
        data = super().clean()
        started, finished = data.get("started_on"), data.get("finished_on")
        if started and finished and finished < started:
            self.add_error("finished_on", "That's before you started.")
        return data


class CheckInForm(forms.Form):
    played_at = forms.DateTimeField(
        label="When",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Leave empty for now.",
    )
    minutes = forms.IntegerField(label="Minutes", required=False, min_value=1, max_value=60 * 24)
    note = forms.CharField(required=False, max_length=280)

    def clean_played_at(self):
        played_at = self.cleaned_data.get("played_at")
        if played_at and played_at > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("That's in the future.")
        return played_at


class ManualItemForm(forms.ModelForm):
    genres = forms.CharField(required=False, max_length=300, help_text="Separated by commas.")

    class Meta:
        model = Item
        fields = ["media_type", "title", "year", "creator", "total", "runtime", "release_date", "genres", "description"]
        labels = {"media_type": "Kind", "total": "Episodes, pages, chapters or tracks", "runtime": "Minutes"}
        widgets = {
            "release_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {"release_date": "If it's still to come, it shows in your calendar."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["genres"] = ", ".join(self.instance.genres)

    def clean_genres(self):
        return [g.strip() for g in self.cleaned_data["genres"].split(",") if g.strip()][:10]


class ListForm(forms.ModelForm):
    media_type = forms.ChoiceField(label="Kind", choices=[("", "Anything")] + MediaType.choices, required=False)
    status = forms.ChoiceField(choices=[("", "Any status")] + Status.choices, required=False)
    min_score = forms.IntegerField(label="Score at least", required=False, min_value=1, max_value=10)
    genre = forms.CharField(required=False, max_length=60)
    year_from = forms.IntegerField(label="From year", required=False, min_value=1800, max_value=2200)
    year_to = forms.IntegerField(label="To year", required=False, min_value=1800, max_value=2200)
    order = forms.ChoiceField(
        choices=[("", "Recently updated"), ("score", "Highest score"), ("year", "Newest first")], required=False
    )

    RULES = ["media_type", "status", "min_score", "genre", "year_from", "year_to", "order"]

    class Meta:
        model = MediaList
        fields = ["name", "description", "is_public", "is_smart"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.RULES:
            self.fields[name].widget.attrs["data-rule"] = ""
            self.initial.setdefault(name, (self.instance.rules or {}).get(name))

    def save(self, commit=True):
        self.instance.rules = {
            k: self.cleaned_data[k] for k in self.RULES if self.cleaned_data.get(k) not in (None, "")
        }
        return super().save(commit)


class CopyForm(forms.ModelForm):
    class Meta:
        model = Copy
        fields = ["format", "resolution", "acquired_on", "note"]
        widgets = {"acquired_on": forms.DateInput(attrs={"type": "date"})}
        labels = {"acquired_on": "Got it on"}


class ImportForm(forms.Form):
    file = forms.FileField(help_text="A CSV export from liveaux, Letterboxd, Goodreads or IMDb.")

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > 20 * 1024 * 1024:
            raise forms.ValidationError("That file is too big. 20 MB at most.")
        return file
