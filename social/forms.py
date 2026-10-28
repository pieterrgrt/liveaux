from django import forms

from .models import COMMENT_MAX, REVIEW_MAX, Comment, Report, Review

SCORE_CHOICES = [("", "No score")] + [(str(n), str(n)) for n in range(10, 0, -1)]


class NameMixin:
    """People without a name are asked for one first: reviews and comments never show an email address."""

    def add_name_field(self, user):
        self.user = user
        if not user.display_name:
            self.fields["display_name"] = forms.CharField(
                label="Your name, as others see it",
                max_length=100,
                help_text="Shown with your reviews and comments. You can change it in your settings.",
            )
            self.order_fields(["display_name"])

    def clean_display_name(self):
        name = self.cleaned_data["display_name"].strip()
        if not name:
            raise forms.ValidationError("Pick a name to show with what you write.")
        return name

    def save_name(self):
        name = self.cleaned_data.get("display_name")
        if name and not self.user.display_name:
            self.user.display_name = name
            self.user.save(update_fields=["display_name"])


class ReviewForm(NameMixin, forms.ModelForm):
    score = forms.TypedChoiceField(
        choices=SCORE_CHOICES,
        coerce=int,
        empty_value=None,
        required=False,
        help_text="1 to 10. The same score as in your library or log.",
    )

    class Meta:
        model = Review
        fields = ["score", "body", "contains_spoilers"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6, "maxlength": REVIEW_MAX})}
        labels = {"body": "Your review"}
        help_texts = {"contains_spoilers": "The review is blurred until someone chooses to read it."}

    def __init__(self, *args, user, score=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_name_field(user)
        if not self.is_bound:
            self.initial["score"] = score or ""
        self.order_fields(["display_name", "score", "body", "contains_spoilers"])

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Write a few words.")
        return body


class CommentForm(NameMixin, forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "maxlength": COMMENT_MAX})}
        labels = {"body": "Comment"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_name_field(user)

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Write something first.")
        return body


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ["reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3, "maxlength": 500})}
        labels = {"reason": "What's wrong with it?"}
