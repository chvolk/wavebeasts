import json
from django.test import TestCase, override_settings
from django.conf import settings

@override_settings(ALLOWED_HOSTS=['testserver'])
class PWATests(TestCase):
    def test_manifest_and_icons(self):
        response=self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/manifest+json')
        data=json.loads(b''.join(response.streaming_content))
        self.assertEqual(data['display'],'standalone')
        self.assertEqual(data['scope'],'/')
        self.assertEqual(data['start_url'],'/me/')
        self.assertTrue({'192x192','512x512'}.issubset({i['sizes'] for i in data['icons']}))
        for icon in data['icons']:
            self.assertTrue((settings.BASE_DIR/'play'/icon['src'].lstrip('/')).exists())
        self.assertTrue(any(i['purpose']=='maskable' for i in data['icons']))

    def test_worker_scope_headers_and_root_favicon(self):
        worker=self.client.get('/service-worker.js')
        self.assertEqual(worker.status_code,200)
        self.assertEqual(worker['Service-Worker-Allowed'],'/')
        self.assertEqual(worker['Cache-Control'],'no-cache')
        self.assertEqual(worker['Content-Type'],'application/javascript')
        worker.close()
        favicon=self.client.get('/favicon.ico')
        self.assertEqual(favicon.status_code,200)
        self.assertEqual(favicon['Content-Type'],'image/x-icon')
        favicon.close()

    def test_page_advertises_installation_and_current_logo(self):
        page=self.client.get('/download/')
        for text in ['rel="manifest"','rel="apple-touch-icon"','brand/mark.svg','pwa/install.js','pwa-install']:
            self.assertContains(page,text)
