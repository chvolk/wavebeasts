from django.test import TestCase, override_settings
from .wiki import PAGES

@override_settings(ALLOWED_HOSTS=['testserver'], SITE_URL='https://wavebeasts.example')
class WikiTests(TestCase):
    def test_pages_are_separate_and_navigable(self):
        for slug, title, _ in PAGES:
            with self.subTest(slug=slug):
                response=self.client.get('/docs/' if slug=='overview' else f'/docs/{slug}/')
                self.assertContains(response, f'<h1>{title.replace("&", "&amp;")}</h1>', html=True)
                self.assertContains(response, 'aria-label="Wiki pages"')
                self.assertContains(response, '/docs/ai-setup/')
                self.assertTemplateUsed(response, f'wiki/{slug}.html')
        overview=self.client.get('/docs/')
        self.assertNotContains(overview, 'id="agent-node"')
        self.assertEqual(self.client.get('/docs/missing/').status_code,404)

    def test_agent_prompts_are_downloadable_and_distinct(self):
        node=self.client.get('/docs/ai-setup/node.txt')
        local=self.client.get('/docs/ai-setup/local.txt')
        for response in (node,local):
            self.assertEqual(response.status_code,200)
            self.assertTrue(response['Content-Type'].startswith('text/plain'))
            self.assertIn('attachment;',response['Content-Disposition'])
            self.assertNotIn(b'{{',response.content)
            self.assertContains(response,'https://wavebeasts.example')
        self.assertContains(node,'/api/account')
        self.assertContains(local,'-addr 127.0.0.1:8777')
        self.assertContains(local,'wavebeast-windows-amd64.exe')
        self.assertNotContains(node,'-addr 127.0.0.1:8777')
        self.assertEqual(self.client.get('/docs/ai-setup/unknown.txt').status_code,404)
        self.assertEqual(self.client.post('/docs/ai-setup/local.txt').status_code,405)
