from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from . import buddy as logic
from .models import Buddy, Node, Wallet
from .tests import _beast


class BuddyChoiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('choices')
        self.start = timezone.now()
        self.buddy = Buddy.objects.create(user=self.user, beast=_beast(self.user),
            hunger=100, energy=100, cleanliness=100, mood=100, refreshed_at=self.start)

    def at(self, minutes):
        return patch('play.buddy.timezone.now', return_value=self.start + timedelta(minutes=minutes))

    def test_rest_blocks_every_action_and_expires_exactly(self):
        with self.at(0):
            logic.apply_care(self.buddy, 'rest')
            for action in logic.CARE:
                self.assertEqual(logic.apply_care(self.buddy, action)['error'], 'cooldown')
        with self.at(19.999):
            self.assertEqual(logic.care_cooldowns(self.buddy)['feed'], 1)
        with self.at(20):
            self.assertIsNone(logic.activity(self.buddy))
            self.assertTrue(logic.apply_care(self.buddy, 'feed')['ok'])
            self.assertEqual(logic.care_cooldowns(self.buddy)['rest'], 1500)

    def test_each_action_locks_other_choices_without_duplicate_rewards(self):
        for action, duration in logic.ACTIVITY_MINUTES.items():
            self.buddy.last_care = {}
            with self.at(0):
                logic.apply_care(self.buddy, action)
                relationship = self.buddy.relationship
                xp = self.buddy.beast.individual_json.get('xp')
                for other in logic.CARE:
                    self.assertIn('error', logic.apply_care(self.buddy, other))
                self.assertEqual(self.buddy.relationship, relationship)
                self.assertEqual(self.buddy.beast.individual_json.get('xp'), xp)
            with self.at(duration):
                self.assertIsNone(logic.activity(self.buddy))

    def test_rest_overlap_and_polling_independence(self):
        with self.at(0):
            logic.apply_care(self.buddy, 'rest')
            self.buddy.save()
        once = Buddy.objects.get(pk=self.buddy.pk)
        for minute in range(1, 61):
            with self.at(minute):
                logic.refresh(self.buddy)
                self.buddy.save()
                self.buddy.refresh_from_db()
        with self.at(60):
            logic.refresh(once)
        for key, rate in logic.VITAL_DECAY_PER_HOUR.items():
            self.assertAlmostEqual(getattr(once, key), 100 - rate * .75)
            self.assertAlmostEqual(getattr(self.buddy, key), getattr(once, key))

    def test_regular_care_can_maintain_near_full_stats_for_a_day(self):
        # One hour cycle, including optional XP training: small short-lived energy tradeoffs.
        schedule = {0: 'feed', 2: 'clean', 4: 'play', 9: 'train', 19: 'rest'}
        minimum = 100
        for minute in range(24 * 60):
            with self.at(minute):
                logic.refresh(self.buddy)
                if minute % 60 in schedule:
                    result = logic.apply_care(self.buddy, schedule[minute % 60])
                    self.assertTrue(result.get('ok'), result)
                minimum = min(minimum, *(getattr(self.buddy, k) for k in logic.VITAL_DECAY_PER_HOUR))
        self.assertGreaterEqual(minimum, 80)
        self.assertGreaterEqual(self.buddy.energy, 95)
        self.assertGreaterEqual(self.buddy.mood, 98)
        self.assertGreaterEqual(self.buddy.hunger, 92)
        self.assertGreaterEqual(self.buddy.cleanliness, 95)

    def test_care_without_training_stays_above_ninety(self):
        schedule = {0: 'feed', 2: 'clean', 4: 'play', 9: 'rest'}
        for minute in range(24 * 60):
            with self.at(minute):
                logic.refresh(self.buddy)
                if minute % 60 in schedule:
                    self.assertTrue(logic.apply_care(self.buddy, schedule[minute % 60]).get('ok'))
                for key in logic.VITAL_DECAY_PER_HOUR:
                    self.assertGreaterEqual(getattr(self.buddy, key), 90)
        with self.at(24 * 60):
            state = logic.state(self.buddy)
            self.assertEqual(state['care_options']['rest']['decay_multiplier'], .25)
            self.assertEqual(state['care_options']['train']['xp_gain'], 40)
            self.assertEqual(state['care_options']['rest']['duration_sec'], 1200)
            self.assertIsInstance(state['energy'], int)

    def test_rest_cannot_be_bypassed_by_other_device_or_reslot(self):
        Wallet.objects.update_or_create(user=self.user, defaults={'subscribed': True})
        nodes = [Node.objects.create(user=self.user, name=name) for name in ['one', 'two']]
        def post(path, data, node):
            return self.client.post('/api/buddy/' + path, data=data,
                content_type='application/json', HTTP_X_WB_NODE_TOKEN=node.token)
        with self.at(0):
            self.assertEqual(post('care', {'action': 'rest'}, nodes[0]).status_code, 200)
            self.assertEqual(post('slot', {'beast_id': None}, nodes[1]).status_code, 200)
            self.assertEqual(post('slot', {'beast_id': self.buddy.beast_id}, nodes[1]).status_code, 200)
            response = post('care', {'action': 'train'}, nodes[1])
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['buddy']['activity']['action'], 'rest')
            self.assertEqual(response.json()['retry_after_sec'], 1200)
