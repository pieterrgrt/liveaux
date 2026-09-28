import django.db.models.deletion
from django.db import migrations, models

CATEGORIES = [
    ("Music", "music"),
    ("Club night", "club"),
    ("Exhibition", "exhibition"),
    ("Film", "film"),
    ("Theatre", "theatre"),
    ("Dance", "dance"),
    ("Comedy", "comedy"),
    ("Talk & reading", "talk"),
    ("Festival", "festival"),
    ("Kids & family", "family"),
    ("Other", "other"),
]


def create_categories(apps, schema_editor):
    Category = apps.get_model("events", "Category")
    Event = apps.get_model("events", "Event")
    EventSubmission = apps.get_model("events", "EventSubmission")
    for position, (name, slug) in enumerate(CATEGORIES):
        Category.objects.get_or_create(slug=slug, defaults={"name": name, "position": position})
    # Until now liveaux was a gig guide: everything that exists is music.
    music = Category.objects.get(slug="music")
    Event.objects.filter(category__isnull=True).update(category=music)
    EventSubmission.objects.filter(category__isnull=True).update(category=music)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0003_cities_submissions"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("slug", models.SlugField(unique=True)),
                (
                    "position",
                    models.PositiveSmallIntegerField(default=0, help_text="Lower comes first in filters."),
                ),
            ],
            options={"verbose_name_plural": "categories", "ordering": ["position", "name"]},
        ),
        migrations.AddField(
            model_name="event",
            name="category",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="events", to="events.category"
            ),
        ),
        migrations.AddField(
            model_name="eventsubmission",
            name="category",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="events.category"
            ),
        ),
        migrations.RunPython(create_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="events", to="events.category"
            ),
        ),
        migrations.AlterField(
            model_name="eventsubmission",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="events.category"
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="ends_at",
            field=models.DateTimeField(
                blank=True,
                help_text="For exhibitions, film runs and festivals: the last day it's on.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="eventsubmission",
            name="ends_at",
            field=models.DateTimeField(blank=True, help_text="Only for things that run several days.", null=True),
        ),
        migrations.AlterField(
            model_name="eventsubmission",
            name="relation",
            field=models.CharField(
                help_text="For example: curator at the museum, or booker at the club.",
                max_length=200,
                verbose_name="your role",
            ),
        ),
        migrations.AlterModelOptions(
            name="promoter",
            options={"ordering": ["name"], "verbose_name": "organiser"},
        ),
        migrations.AlterField(
            model_name="event",
            name="promoter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="events",
                to="events.promoter",
                verbose_name="organiser",
            ),
        ),
    ]
