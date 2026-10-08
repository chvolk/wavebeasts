from django.contrib.auth.models import User
from django.test import TestCase
from .models import Wallet


class TutorialTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('new-player', password='test-password')
        self.client.force_login(self.user)

    def test_first_login_and_dismissal_persist_across_sessions(self):
        response = self.client.get('/me/')
        self.assertContains(response, 'data-first="true"')
        response = self.client.post('/onboarding/', HTTP_ACCEPT='application/json')
        self.assertJSONEqual(response.content, {'ok': True})
        self.assertTrue(Wallet.objects.get(user=self.user).onboarded)
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get('/me/')
        self.assertContains(response, 'data-first="false"')
        self.assertContains(response, 'Replay tutorial')

    def test_anonymous_visitors_do_not_get_tour(self):
        self.client.logout()
        self.assertNotContains(self.client.get('/'), 'data-wb-tutorial')
        self.assertEqual(self.client.post('/onboarding/', HTTP_ACCEPT='application/json').status_code, 302)

    def test_existing_onboarding_form_still_works(self):
        self.assertRedirects(self.client.post('/onboarding/'), '/me/')
