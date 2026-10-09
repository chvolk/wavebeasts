from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase

from .names import player_name


class PlayerNameTests(TestCase):
    def test_prefers_synced_clerk_name(self):
        u = User(username="user_3JcTRYdGOb9eT0pYHas4okblh9Y", first_name="chambersvolk", email="c@example.com")
        self.assertEqual(player_name(u), "chambersvolk")

    def test_falls_back_to_email_then_masked_id(self):
        self.assertEqual(player_name(User(username="user_abcd1234", email="cvolk@example.com")), "cvolk")
        self.assertEqual(player_name(User(username="user_abcd1234")), "Trainer 1234")
        self.assertEqual(player_name(User(username="legacy")), "legacy")

    def test_template_filter_never_shows_clerk_id(self):
        u = User.objects.create_user("user_zzzz9999", first_name="Zed")
        out = Template("{% load players %}by {{ u|player_name }}").render(Context({"u": u}))
        self.assertEqual(out, "by Zed")
        self.assertNotIn("user_", out)
