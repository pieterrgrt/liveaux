import json
from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Category, City, Event, Venue
from library.models import Entry, Item, MediaType, Source, Status
from logbook.models import LogEntry

from .admin import ReportAdmin
from .models import Comment, Like, Report, Review


class SocialTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fan = User.objects.create_user("fan@example.com", "pw", display_name="Pieter")
        cls.other = User.objects.create_user("other@example.com", "pw", display_name="Mila")
        cls.nameless = User.objects.create_user("nameless@example.com", "pw")
        cls.staff = User.objects.create_user("staff@example.com", "pw", display_name="Mod", is_staff=True)
        city = City.objects.create(name="Berlin", slug="berlin")
        venue = Venue.objects.create(name="SO36", city=city)
        music = Category.objects.get(slug="music")
        cls.past = Event.objects.create(
            category=music, title="Punk Night", venue=venue, starts_at=timezone.now() - timedelta(days=2)
        )
        cls.future = Event.objects.create(
            category=music, title="Next Week", venue=venue, starts_at=timezone.now() + timedelta(days=7)
        )
        cls.film = Item.objects.create(
            media_type=MediaType.MOVIE, source=Source.TMDB, source_id="1", title="Past Lives", year=2023
        )
        cls.diary = Item.objects.create(media_type=MediaType.BOOK, title="My diary", created_by=cls.other)

    def review(self, user=None, target=None, body="Good.", **kwargs):
        target = target or self.film
        field = "item" if isinstance(target, Item) else "event"
        return Review.objects.create(user=user or self.other, body=body, **{field: target}, **kwargs)

    def write_url(self, target):
        kind = "item" if isinstance(target, Item) else "event"
        return reverse("social:write_review", args=[kind, target.pk])


class ConstraintTests(SocialTestCase):
    def test_review_needs_exactly_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(user=self.fan, body="Nothing")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(user=self.fan, body="Both", item=self.film, event=self.past)

    def test_one_review_per_user_per_target(self):
        self.review(self.fan)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.review(self.fan)
        # A review of an event and one of an item by the same person is fine.
        self.review(self.fan, self.past)
        self.review(self.other, self.past)
        self.assertEqual(Review.objects.count(), 3)

    def test_comment_needs_exactly_one_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Comment.objects.create(user=self.fan, body="?")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Comment.objects.create(user=self.fan, body="?", item=self.film, event=self.past)

    def test_one_like_per_user(self):
        review = self.review()
        Like.objects.create(user=self.fan, review=review)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Like.objects.create(user=self.fan, review=review)

    def test_report_needs_exactly_one_target(self):
        review = self.review()
        comment = Comment.objects.create(user=self.other, body="Hi", event=self.past)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Report.objects.create(reporter=self.fan, review=review, comment=comment)


class ReviewTests(SocialTestCase):
    def setUp(self):
        self.client.force_login(self.fan)

    def test_review_an_item_saves_the_score_in_the_library(self):
        response = self.client.post(self.write_url(self.film), {"score": "8", "body": "Quietly devastating."})
        self.assertRedirects(response, f"{self.film.get_absolute_url()}#reviews")
        review = Review.objects.get()
        self.assertEqual((review.user, review.item, review.body), (self.fan, self.film, "Quietly devastating."))
        entry = Entry.objects.get(user=self.fan, item=self.film)
        self.assertEqual((entry.score, entry.status), (8, Status.COMPLETED))
        self.assertEqual(review.score, 8)

    def test_editing_updates_the_existing_entry_score(self):
        Entry.objects.create(user=self.fan, item=self.film, status=Status.IN_PROGRESS, score=5)
        self.client.post(self.write_url(self.film), {"score": "9", "body": "Better the second time."})
        self.client.post(self.write_url(self.film), {"score": "7", "body": "Hm.", "contains_spoilers": "on"})
        entry = Entry.objects.get(user=self.fan, item=self.film)
        self.assertEqual((entry.score, entry.status), (7, Status.IN_PROGRESS))
        review = Review.objects.get()
        self.assertEqual((review.body, review.contains_spoilers), ("Hm.", True))

    def test_score_changes_in_the_library_show_on_the_review(self):
        review = self.review(self.fan)
        Entry.objects.create(user=self.fan, item=self.film, score=6)
        self.assertEqual(Review.objects.with_numbers().get(pk=review.pk).score, 6)
        self.assertContains(self.client.get(review.get_absolute_url()), "6<span>/10</span>", html=False)

    def test_review_form_shows_current_score(self):
        Entry.objects.create(user=self.fan, item=self.film, score=4)
        response = self.client.get(self.film.get_absolute_url())
        self.assertContains(response, '<option value="4" selected>4</option>', html=True)

    def test_review_an_event_saves_the_rating_in_the_log(self):
        self.client.post(self.write_url(self.past), {"score": "9", "body": "Loud."})
        self.assertEqual(LogEntry.objects.get(user=self.fan, event=self.past).rating, 9)
        self.assertTrue(Review.objects.filter(event=self.past, user=self.fan).exists())

    def test_cannot_review_an_event_before_it_starts(self):
        self.client.post(self.write_url(self.future), {"score": "9", "body": "Can't wait."})
        self.assertFalse(Review.objects.exists())
        self.assertFalse(LogEntry.objects.exists())
        self.assertContains(self.client.get(self.future.get_absolute_url()), "Reviews open once it has started")

    def test_score_is_optional_and_body_is_required(self):
        self.client.post(self.write_url(self.film), {"score": "", "body": "   "})
        self.assertFalse(Review.objects.exists())
        self.client.post(self.write_url(self.film), {"score": "", "body": "No number for this one."})
        self.assertIsNone(Review.objects.get().score)

    def test_body_has_a_max_length(self):
        self.client.post(self.write_url(self.film), {"body": "x" * 5001})
        self.assertFalse(Review.objects.exists())

    def test_logged_out_cannot_review(self):
        self.client.logout()
        response = self.client.post(self.write_url(self.film), {"body": "Hi"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response.url)
        self.assertFalse(Review.objects.exists())

    def test_cannot_review_someone_elses_hand_added_item(self):
        response = self.client.post(self.write_url(self.diary), {"body": "Snooping."})
        self.assertEqual(response.status_code, 404)

    def test_delete_own_review_keeps_the_score(self):
        self.client.post(self.write_url(self.film), {"score": "8", "body": "Yes."})
        review = Review.objects.get()
        other = self.review(self.other)
        self.client.post(reverse("social:delete_review", args=[other.pk]))
        self.assertTrue(Review.objects.filter(pk=other.pk).exists())
        self.client.post(reverse("social:delete_review", args=[review.pk]))
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertEqual(Entry.objects.get(user=self.fan, item=self.film).score, 8)

    def test_nameless_user_is_asked_for_a_name(self):
        self.client.force_login(self.nameless)
        response = self.client.get(self.film.get_absolute_url())
        self.assertContains(response, "Your name, as others see it")
        self.client.post(self.write_url(self.film), {"body": "Nice."})
        self.assertFalse(Review.objects.exists())
        self.client.post(self.write_url(self.film), {"display_name": "Noor", "body": "Nice."})
        self.nameless.refresh_from_db()
        self.assertEqual(self.nameless.display_name, "Noor")
        self.assertEqual(Review.objects.get().user, self.nameless)

    def test_named_user_is_not_asked(self):
        self.assertNotContains(self.client.get(self.film.get_absolute_url()), "Your name, as others see it")

    def test_average_and_sorting(self):
        a = self.review(self.other, body="First")
        b = self.review(self.staff, body="Second")
        Entry.objects.create(user=self.other, item=self.film, score=6)
        Entry.objects.create(user=self.staff, item=self.film, score=9)
        # A score without a review doesn't count: only reviews are public.
        Entry.objects.create(user=self.nameless, item=self.film, score=1)
        Like.objects.create(user=self.fan, review=a)
        response = self.client.get(self.film.get_absolute_url())
        self.assertContains(response, '<span class="review-average">7.5</span>', html=True)
        content = response.content.decode()
        self.assertLess(content.index("Second"), content.index("First"))
        content = self.client.get(self.film.get_absolute_url() + "?reviews=liked").content.decode()
        self.assertLess(content.index("First"), content.index("Second"))
        self.assertTrue(b)

    def test_review_page_takes_the_side_of_its_target(self):
        item_review = self.review(self.other)
        event_review = self.review(self.other, self.past)
        self.assertContains(self.client.get(item_review.get_absolute_url()), 'data-side="aux"')
        self.assertContains(self.client.get(event_review.get_absolute_url()), 'data-side="live"')


class LikeTests(SocialTestCase):
    def setUp(self):
        self.client.force_login(self.fan)
        self.target = self.review(self.other)

    def test_toggle(self):
        url = reverse("social:like", args=[self.target.pk])
        self.client.post(url)
        self.assertEqual(self.target.likes.count(), 1)
        self.assertContains(self.client.get(self.target.get_absolute_url()), "Liked · 1")
        self.client.post(url)
        self.assertEqual(self.target.likes.count(), 0)

    def test_cannot_like_own_review(self):
        own = self.review(self.fan, self.past)
        self.client.post(reverse("social:like", args=[own.pk]))
        self.assertFalse(own.likes.exists())

    def test_next_must_be_on_liveaux(self):
        response = self.client.post(reverse("social:like", args=[self.target.pk]), {"next": "https://evil.example/"})
        self.assertEqual(response.url, self.target.get_absolute_url())

    def test_logged_out_cannot_like(self):
        self.client.logout()
        self.client.post(reverse("social:like", args=[self.target.pk]))
        self.assertFalse(self.target.likes.exists())


class CommentTests(SocialTestCase):
    def setUp(self):
        self.client.force_login(self.fan)

    def test_comment_on_review_event_and_item(self):
        review = self.review(self.other)
        for kind, target in [("review", review), ("event", self.past), ("item", self.film)]:
            response = self.client.post(reverse("social:add_comment", args=[kind, target.pk]), {"body": f"On {kind}"})
            comment = Comment.objects.latest("pk")
            self.assertEqual(comment.target, target)
            self.assertRedirects(response, comment.get_absolute_url(), fetch_redirect_response=False)
        self.assertContains(self.client.get(review.get_absolute_url()), "On review")
        self.assertContains(self.client.get(self.past.get_absolute_url()), "On event")
        self.assertContains(self.client.get(self.film.get_absolute_url()), "On item")

    def test_future_events_can_have_comments(self):
        self.client.post(reverse("social:add_comment", args=["event", self.future.pk]), {"body": "Anyone going?"})
        self.assertContains(self.client.get(self.future.get_absolute_url()), "Anyone going?")

    def test_delete_own_only(self):
        mine = Comment.objects.create(user=self.fan, body="Mine", event=self.past)
        theirs = Comment.objects.create(user=self.other, body="Theirs", event=self.past)
        self.client.post(reverse("social:delete_comment", args=[theirs.pk]))
        self.client.post(reverse("social:delete_comment", args=[mine.pk]))
        self.assertEqual(list(Comment.objects.all()), [theirs])

    def test_logged_out_cannot_comment(self):
        self.client.logout()
        self.client.post(reverse("social:add_comment", args=["event", self.past.pk]), {"body": "Hi"})
        self.assertFalse(Comment.objects.exists())
        self.assertContains(self.client.get(self.past.get_absolute_url()), "to join in")

    def test_nameless_user_must_choose_a_name(self):
        self.client.force_login(self.nameless)
        url = reverse("social:add_comment", args=["event", self.past.pk])
        self.client.post(url, {"body": "Hi"})
        self.assertFalse(Comment.objects.exists())
        self.client.post(url, {"body": "Hi", "display_name": "Noor"})
        self.assertEqual(Comment.objects.get().user.display_name, "Noor")

    def test_never_shows_email(self):
        self.client.force_login(self.nameless)
        Comment.objects.create(user=self.nameless, body="Hello there", event=self.past)
        self.review(self.nameless, self.past, body="Not bad")
        self.client.logout()
        response = self.client.get(self.past.get_absolute_url())
        self.assertContains(response, "Hello there")
        self.assertNotContains(response, "nameless@example.com")
        self.assertContains(response, "A liveaux fan")

    @override_settings(SOCIAL_LIMITS={"comment": (3, 60)})
    def test_rate_limit(self):
        url = reverse("social:add_comment", args=["event", self.past.pk])
        for n in range(5):
            self.client.post(url, {"body": f"Comment {n}"})
        self.assertEqual(Comment.objects.count(), 3)
        # A minute later it's fine again.
        Comment.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.client.post(url, {"body": "Later"})
        self.assertEqual(Comment.objects.count(), 4)

    @override_settings(SOCIAL_LIMITS={"review": (1, 600)})
    def test_review_rate_limit(self):
        self.client.post(self.write_url(self.film), {"body": "One"})
        self.client.post(self.write_url(self.past), {"body": "Two"})
        self.assertEqual(Review.objects.count(), 1)
        # Editing an existing review isn't limited.
        self.client.post(self.write_url(self.film), {"body": "One, edited"})
        self.assertEqual(Review.objects.get().body, "One, edited")


class ModerationTests(SocialTestCase):
    def setUp(self):
        self.bad = self.review(self.other, body="Something nasty")
        self.bad_comment = Comment.objects.create(user=self.other, body="Nasty comment", event=self.past)

    def test_report_review_and_comment(self):
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(reverse("social:report", args=["review", self.bad.pk])).status_code, 200)
        self.client.post(reverse("social:report", args=["review", self.bad.pk]), {"reason": "Rude"})
        self.client.post(reverse("social:report", args=["review", self.bad.pk]), {"reason": "Again"})
        self.client.post(reverse("social:report", args=["comment", self.bad_comment.pk]), {"reason": ""})
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(Report.objects.get(review=self.bad).reason, "Rude")

    def test_cannot_report_own(self):
        self.client.force_login(self.other)
        self.client.post(reverse("social:report", args=["review", self.bad.pk]), {"reason": "Me"})
        self.assertFalse(Report.objects.exists())

    def test_hidden_review_disappears_except_for_staff(self):
        Review.objects.filter(pk=self.bad.pk).update(is_hidden=True)
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(self.bad.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(self.film.get_absolute_url()), "Something nasty")
        self.assertNotContains(self.client.get(reverse("social:person", args=[self.other.pk])), "Something nasty")
        self.client.post(reverse("social:like", args=[self.bad.pk]))
        self.assertFalse(Like.objects.exists())
        self.client.post(reverse("social:add_comment", args=["review", self.bad.pk]), {"body": "?"})
        self.assertFalse(Comment.objects.filter(review=self.bad).exists())
        # The writer doesn't see it either, but is told.
        self.client.force_login(self.other)
        response = self.client.get(self.film.get_absolute_url())
        self.assertNotContains(response, "Something nasty")
        self.assertContains(response, "A moderator hid your review")
        # Staff still see it, marked.
        self.client.force_login(self.staff)
        response = self.client.get(self.bad.get_absolute_url())
        self.assertContains(response, "Something nasty")
        self.assertContains(response, "Hidden")

    def test_hidden_comment_disappears_except_for_staff(self):
        Comment.objects.filter(pk=self.bad_comment.pk).update(is_hidden=True)
        self.assertNotContains(self.client.get(self.past.get_absolute_url()), "Nasty comment")
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.past.get_absolute_url()), "Nasty comment")

    def test_staff_hide_on_the_page(self):
        Report.objects.create(reporter=self.fan, comment=self.bad_comment)
        url = reverse("social:hide", args=["comment", self.bad_comment.pk])
        self.client.force_login(self.fan)
        self.client.post(url)
        self.bad_comment.refresh_from_db()
        self.assertFalse(self.bad_comment.is_hidden)
        self.client.force_login(self.staff)
        self.client.post(url)
        self.bad_comment.refresh_from_db()
        self.assertTrue(self.bad_comment.is_hidden)
        self.assertEqual(Report.objects.get().status, Report.Status.HIDDEN)

    def _admin_action(self, action, queryset):
        request = RequestFactory().post("/admin/")
        request.user = self.staff
        request._messages = type("M", (), {"add": lambda *a, **k: None})()
        admin = ReportAdmin(Report, AdminSite())
        getattr(admin, action)(request, queryset)

    def test_admin_hide_and_dismiss(self):
        first = Report.objects.create(reporter=self.fan, review=self.bad)
        second = Report.objects.create(reporter=self.staff, review=self.bad)
        other = Report.objects.create(reporter=self.fan, comment=self.bad_comment)
        self._admin_action("hide_content", Report.objects.filter(pk=first.pk))
        self.bad.refresh_from_db()
        self.assertTrue(self.bad.is_hidden)
        self.assertEqual(
            set(Report.objects.filter(review=self.bad).values_list("status", flat=True)), {Report.Status.HIDDEN}
        )
        self._admin_action("dismiss", Report.objects.filter(pk=other.pk))
        other.refresh_from_db()
        self.bad_comment.refresh_from_db()
        self.assertEqual(other.status, Report.Status.DISMISSED)
        self.assertFalse(self.bad_comment.is_hidden)
        self.assertEqual(other.resolved_by, self.staff)
        self.assertTrue(second)

    def test_admin_pages_render(self):
        Report.objects.create(reporter=self.fan, review=self.bad, reason="Rude")
        Like.objects.create(user=self.fan, review=self.bad)
        superuser = User.objects.create_superuser("admin@example.com", "pw")
        self.client.force_login(superuser)
        for name in ["review", "comment", "like", "report"]:
            response = self.client.get(reverse(f"admin:social_{name}_changelist"))
            self.assertEqual(response.status_code, 200, name)
        self.assertContains(self.client.get(reverse("admin:social_report_changelist")), "Something nasty")
        response = self.client.get(reverse("admin:social_review_change", args=[self.bad.pk]))
        self.assertEqual(response.status_code, 200)


class PrivacyTests(SocialTestCase):
    def test_reviews_of_hand_added_items_stay_private(self):
        private = self.review(self.other, self.diary, body="Dear diary")
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(private.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("social:person", args=[self.other.pk])), "Dear diary")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(private.get_absolute_url()), "Dear diary")

    def test_export_includes_social(self):
        review = self.review(self.fan, body="My words")
        Entry.objects.create(user=self.fan, item=self.film, score=7)
        Comment.objects.create(user=self.fan, body="My comment", event=self.past)
        Like.objects.create(user=self.fan, review=self.review(self.other, self.past))
        Report.objects.create(reporter=self.fan, review=self.review(self.staff), reason="Spam")
        self.client.force_login(self.fan)
        data = json.loads(self.client.get(reverse("accounts:export")).content)
        self.assertEqual(data["reviews"][0]["review"], "My words")
        self.assertEqual(data["reviews"][0]["score"], 7)
        self.assertEqual(data["comments"][0]["comment"], "My comment")
        self.assertEqual(len(data["liked_reviews"]), 1)
        self.assertEqual(data["reports"][0]["reason"], "Spam")
        self.assertTrue(review)

    def test_deleting_the_account_removes_social(self):
        review = self.review(self.fan)
        Comment.objects.create(user=self.fan, body="x", review=self.review(self.other, self.past))
        Comment.objects.create(user=self.other, body="reply", review=review)
        Like.objects.create(user=self.fan, review=Review.objects.get(user=self.other))
        Like.objects.create(user=self.other, review=review)
        Report.objects.create(reporter=self.fan, review=Review.objects.get(user=self.other))
        self.client.force_login(self.fan)
        self.client.post(reverse("accounts:delete"), {"password": "pw", "confirm": "on"})
        self.assertFalse(User.objects.filter(email="fan@example.com").exists())
        self.assertFalse(Review.objects.filter(user__email="fan@example.com").exists())
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Comment.objects.count(), 0)  # theirs went with my review
        self.assertEqual(Like.objects.count(), 0)
        self.assertEqual(Report.objects.count(), 0)


class PageTests(SocialTestCase):
    def test_pages_render_logged_out(self):
        review = self.review(self.other, self.past, body="Sweaty and great")
        Comment.objects.create(user=self.fan, body="Agreed", review=review)
        item_review = self.review(self.other, body="Lovely film", contains_spoilers=True)
        response = self.client.get(review.get_absolute_url())
        self.assertContains(response, "Sweaty and great")
        self.assertContains(response, "Agreed")
        self.assertContains(response, 'property="og:title"')
        self.assertContains(response, "data-share")
        # Item reviews are public on their own page, and link previews show the cover.
        response = self.client.get(item_review.get_absolute_url())
        self.assertContains(response, "Lovely film")
        self.assertContains(response, "Spoilers · show")
        self.assertContains(response, 'content="Contains spoilers."')
        response = self.client.get(reverse("social:person", args=[self.other.pk]))
        self.assertContains(response, "Sweaty and great")
        self.assertContains(response, "Lovely film")
        self.assertContains(response, "Mila")

    def test_event_page_has_reviews_share_and_meta(self):
        self.review(self.other, self.past, body="Sweaty and great")
        response = self.client.get(self.past.get_absolute_url())
        self.assertContains(response, 'id="reviews"')
        self.assertContains(response, "Sweaty and great")
        self.assertContains(response, 'property="og:url" content="http://testserver/events/')
        self.assertContains(response, "data-share")

    def test_item_page_meta_uses_absolute_cover(self):
        Item.objects.filter(pk=self.film.pk).update(cover_url="https://image.example/p.jpg")
        self.client.force_login(self.fan)
        response = self.client.get(self.film.get_absolute_url())
        self.assertContains(response, f'content="http://testserver{reverse("library:cover", args=[self.film.pk])}"')
        self.assertContains(response, "Write a review")

    def test_latest_reviews_on_overviews(self):
        self.review(self.other, self.past, body="Event words")
        self.review(self.other, body="Film words")
        self.review(self.other, self.diary, body="Diary words")
        response = self.client.get(reverse("live"))
        self.assertContains(response, "Latest reviews")
        self.assertContains(response, "Event words")
        self.assertNotContains(response, "Film words")
        self.client.force_login(self.fan)
        Entry.objects.create(user=self.fan, item=self.film)
        response = self.client.get(reverse("library:index"))
        self.assertContains(response, "Film words")
        self.assertNotContains(response, "Diary words")
        self.assertNotContains(response, "Event words")

    def test_public_lists_link_to_reviews(self):
        User.objects.filter(pk=self.other.pk).update(log_is_public=True, library_is_public=True)
        for name in ["logbook:public", "library:public"]:
            response = self.client.get(reverse(name, args=[self.other.pk]))
            self.assertContains(response, reverse("social:person", args=[self.other.pk]))
            self.assertContains(response, "data-share")

    def test_unknown_kinds_are_404(self):
        self.client.force_login(self.fan)
        self.assertEqual(self.client.post(reverse("social:write_review", args=["venue", 1]), {}).status_code, 404)
        self.assertEqual(self.client.post(reverse("social:add_comment", args=["venue", 1]), {}).status_code, 404)
        self.assertEqual(self.client.get(reverse("social:report", args=["event", 1])).status_code, 404)

    def test_standalone_review_form(self):
        self.client.force_login(self.fan)
        response = self.client.get(self.write_url(self.past))
        self.assertContains(response, "Write a review")
        self.assertContains(response, 'data-side="live"')
        response = self.client.post(self.write_url(self.past), {"body": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
