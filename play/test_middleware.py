from django.contrib.auth.models import User
from django.test import Client, TestCase


class NoStoreMiddlewareTests(TestCase):
    def test_signed_in_pages_are_not_cached(self):
        user = User.objects.create_user("user_mw", password="x")
        c = Client()
        c.force_login(user)
        r = c.get("/battle/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "private, no-store")

    def test_anonymous_pages_untouched(self):
        r = Client().get("/privacy/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Cache-Control", r)
