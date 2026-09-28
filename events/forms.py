from django import forms

from .models import Artist, Event, Membership, Promoter, Venue

PAGE_FIELDS = {
    "venue": ["name", "address", "district", "website", "description"],
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
