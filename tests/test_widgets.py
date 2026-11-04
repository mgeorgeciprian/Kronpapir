"""Widget endpoints /api/curs, /api/vreme, /api/aer. Upstream calls are mocked.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_widgets -v
"""
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['FLASK_SECRET_KEY'] = 'fake-test-secret'
os.environ['ADMIN_PASSWORD'] = 'fake-test-password'
os.environ.pop('ANTHROPIC_API_KEY', None)

from web import app as webapp  # noqa: E402

BNR = b'''<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd"><Header><Publisher>BNR</Publisher></Header>
<Body><OrigCurrency>RON</OrigCurrency><Cube date="2026-11-04">
<Rate currency="EUR">5.3443</Rate><Rate currency="GBP">6.4050</Rate>
<Rate currency="HUF" multiplier="100">1.3000</Rate><Rate currency="USD">4.7518</Rate>
</Cube></Body></DataSet>'''
WEATHER = json.dumps({'current': {'temperature_2m': 6.8, 'weather_code': 3}}).encode()


def answer(body):
    return mock.MagicMock(__enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False)


class WidgetTests(unittest.TestCase):
    def setUp(self):
        webapp._widget_cache.clear()
        self.client = webapp.app.test_client()
        patcher = mock.patch.object(webapp.urllib.request, 'urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        clock = mock.patch.object(webapp.time, 'time', return_value=1000000.0)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def test_curs_bnr(self):
        self.urlopen.return_value = answer(BNR)
        r = self.client.get('/api/curs')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json, {'date': '2026-11-04',
                                  'rates': {'EUR': 5.3443, 'USD': 4.7518, 'GBP': 6.405}})
        self.assertIn('max-age', r.headers['Cache-Control'])

    def test_curs_old_http_namespace_also_works(self):
        self.urlopen.return_value = answer(BNR.replace(b'https://www.bnr.ro', b'http://www.bnr.ro'))
        self.assertEqual(self.client.get('/api/curs').status_code, 200)

    def test_vreme_keeps_open_meteo_shape(self):
        self.urlopen.return_value = answer(WEATHER)
        self.assertEqual(self.client.get('/api/vreme').json['current']['weather_code'], 3)

    def test_aer(self):
        self.urlopen.return_value = answer(b'{"current": {"european_aqi": 38}}')
        self.assertEqual(self.client.get('/api/aer').json['current']['european_aqi'], 38)

    def test_cache_avoids_second_call(self):
        self.urlopen.return_value = answer(WEATHER)
        self.client.get('/api/vreme')
        self.client.get('/api/vreme')
        self.assertEqual(self.urlopen.call_count, 1)

    def test_failure_without_cache_is_503_and_backs_off(self):
        self.urlopen.side_effect = OSError('timeout')
        self.assertEqual(self.client.get('/api/curs').status_code, 503)
        self.assertEqual(self.client.get('/api/curs').status_code, 503)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_recovers_after_retry_window(self):
        self.urlopen.side_effect = OSError('timeout')
        self.client.get('/api/vreme')
        self.urlopen.side_effect = None
        self.urlopen.return_value = answer(WEATHER)
        self.clock.return_value += webapp.WIDGET_RETRY_SECONDS + 1
        self.assertEqual(self.client.get('/api/vreme').status_code, 200)

    def test_stale_value_served_when_refresh_fails(self):
        self.urlopen.return_value = answer(WEATHER)
        self.client.get('/api/vreme')
        self.clock.return_value += 1000
        self.urlopen.side_effect = OSError('timeout')
        self.assertEqual(self.client.get('/api/vreme').status_code, 200)

    def test_too_old_value_is_dropped(self):
        self.urlopen.return_value = answer(WEATHER)
        self.client.get('/api/vreme')
        self.clock.return_value += 7 * 3600
        self.urlopen.side_effect = OSError('timeout')
        self.assertEqual(self.client.get('/api/vreme').status_code, 503)

    def test_incomplete_bnr_feed_is_rejected(self):
        self.urlopen.return_value = answer(BNR.replace(b'<Rate currency="USD">4.7518</Rate>', b''))
        self.assertEqual(self.client.get('/api/curs').status_code, 503)

    def test_garbage_html_from_bnr_is_rejected(self):
        self.urlopen.return_value = answer(b'<html><body>pagina</body>')
        self.assertEqual(self.client.get('/api/curs').status_code, 503)


if __name__ == '__main__':
    unittest.main()
