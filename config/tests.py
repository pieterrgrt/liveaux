from unittest import mock

from django.test import TestCase, override_settings


class HealthTests(TestCase):
    def test_health_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @override_settings(SECURE_SSL_REDIRECT=True, ALLOWED_HOSTS=["liveaux.eu"])
    def test_health_skips_https_redirect_and_host_check(self):
        response = self.client.get("/health", HTTP_HOST="127.0.0.1:8001")
        self.assertEqual(response.status_code, 200)

    def test_health_reports_unreachable_database(self):
        with mock.patch("config.health.connection.cursor", side_effect=Exception("down")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)


class RouteTests(TestCase):
    def test_home(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_home_links_icons(self):
        response = self.client.get("/")
        self.assertContains(response, 'rel="apple-touch-icon"')
        self.assertContains(response, "events/icons/icon.svg")
        self.assertContains(response, 'class="logo-e"', count=2)

    def test_privacy(self):
        self.assertEqual(self.client.get("/privacy/").status_code, 200)
