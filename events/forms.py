from django import forms
from django.utils import timezone

from .models import Artist, City, Event, EventSubmission, Membership, Promoter, Venue

PAGE_FIELDS = {
    "venue": ["name", "address", "district", "city", "website", "description"],
    "promoter": ["name", "description", "website"],
    "artist": ["name", "hometown", "description", "website"],
}


def page_form_class(model):
    return forms.modelform_factory(model, fields=PAGE_FIELDS[model.kind])


class EventForm(forms.ModelForm):
    """Event form for a venue or promoter. The page the event belongs to is fixed and not shown."""

    class Meta:
        model = Event
        fields = ["title", "starts_at", "venue", "promoter", "artists", "price", "ticket_url", "description"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "artists": forms.SelectMultiple(attrs={"size": 6}),
        }
        labels = {"starts_at": "Starts at", "ticket_url": "Ticket link", "price": "Price (€)"}
        help_texts = {"artists": "Hold Ctrl (Cmd on a Mac) to select more than one."}

    def __init__(self, *args, fixed_page=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixed_page = fixed_page
        if isinstance(fixed_page, Venue):
            del self.fields["venue"]
        elif isinstance(fixed_page, Promoter):
            del self.fields["promoter"]
        self.fields["artists"].queryset = Artist.objects.all()

    def save(self, commit=True):
        event = super().save(commit=False)
        if isinstance(self.fixed_page, Venue):
            event.venue = self.fixed_page
        elif isinstance(self.fixed_page, Promoter):
            event.promoter = self.fixed_page
        if commit:
            event.save()
            self.save_m2m()
        return event


class AddMemberForm(forms.Form):
    email = forms.EmailField(label="Email address")
    role = forms.ChoiceField(choices=Membership.ROLE_CHOICES, initial=Membership.EDITOR)


class EventSubmissionForm(forms.ModelForm):
    """Public form for venues without a liveaux page. Submissions wait for approval in the admin."""

    class Meta:
        model = EventSubmission
        fields = [
            "venue",
            "new_venue_name",
            "new_venue_address",
            "new_venue_district",
            "new_venue_city",
            "title",
            "starts_at",
            "price",
            "ticket_url",
            "description",
            "relation",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }
        labels = {
            "starts_at": "Starts at",
            "ticket_url": "Ticket link",
            "price": "Price (€)",
            "title": "Event title",
        }
        help_texts = {"venue": "Not in the list? Leave this empty and fill in the new venue below."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["venue"].queryset = Venue.objects.select_related("city")
        self.fields["venue"].label_from_instance = lambda v: f"{v.name} ({v.city})"
        self.fields["new_venue_city"].queryset = City.objects.all()

    def clean(self):
        data = super().clean()
        if data.get("venue"):
            for field in ("new_venue_name", "new_venue_address", "new_venue_district"):
                data[field] = ""
            data["new_venue_city"] = None
        else:
            if not data.get("new_venue_name"):
                self.add_error("new_venue_name", "Pick a venue above, or give the name of the new venue.")
            if not data.get("new_venue_city"):
                self.add_error("new_venue_city", "Which city is the new venue in?")
        starts_at = data.get("starts_at")
        if starts_at and starts_at < timezone.now():
            self.add_error("starts_at", "This date is in the past.")
        return data
