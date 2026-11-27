"""Locuri de muncă AJOFM: colectare, curățarea datelor, pagini, JobPosting, sitemap.

Run: python -m pytest tests/test_jobs.py -q
Fără rețea: clientul HTTP e înlocuit cu unul fals; datele stau într-un folder temporar.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ['FLASK_SECRET_KEY'] = 'fake-test-secret'
os.environ['ADMIN_PASSWORD'] = 'fake-test-password'

from sources import ajofm  # noqa: E402
from sources.http import FetchError, PoliteClient  # noqa: E402
from web import app as webapp  # noqa: E402
from web import jobs as jobs_web  # noqa: E402

TZ = ZoneInfo('Europe/Bucharest')
NOW = datetime(2026, 11, 26, 14, 0, tzinfo=TZ)


def row(job_id, **extra):
    base = {
        'id': job_id, 'county_id': 9, 'occupation': 'CONDUCATOR AUTO TRANSPORT RUTIER DE MARFURI',
        'cor_name': '833201 - Conducător auto transport rutier de mărfuri',
        'employer_name': 'FIRMA TEST SRL', 'employer_tax_code': '12345678',
        'job_domain_name': 'Servicii transport / curierat',
        'address_locality_name': 'Brașov > MUNICIPIUL BRASOV > BRASOV',
        'address_street': 'MIHAIL KOGALNICEANU ', 'address_street_number': '4',
        'address_appartment': '01', 'address_building_floor': 'PARTER',
        'contact_name': 'Ion Popescu', 'contact_phone': '0747000000', 'contact_email': 'ion@firma.ro',
        'minimum_salary': '4400.00', 'maximum_salary': '6000.00', 'salary_type': 'gross',
        'open_positions': 3, 'offer_available_eu_citizens': True,
        'contract_type_name': 'Cu durată nedeterminată', 'work_type_name': 'Cu normă întreagă',
        'work_regime_name': 'Sediu', 'education_level_name': 'Gimnazial',
        'professional_experience_name': 'Fără experiență - 0 ani', 'job_posting_target_name': 'PCLM',
        'job_offer_closing_name': 'Interviu', 'description': None,
        'created_at': '2026-11-24 13:30:25', 'job_start_date': '2026-11-24', 'job_expiry_date': '2027-01-24',
    }
    base.update(extra)
    return base



def all_sitemaps(client):
    """Textul tuturor sitemap-urilor din indexul /sitemap.xml, lipite."""
    index = client.get('/sitemap.xml').get_data(as_text=True)
    paths = re.findall(r'<loc>https://kronpapir\.ro(/[^<]+)</loc>', index)
    return '\n'.join(client.get(p).get_data(as_text=True) for p in paths)

class FakeClient:
    """Imită API-ul: întoarce rândurile pe pagini."""
    def __init__(self, rows, total=None):
        self.rows, self.total, self.requests_made, self.payloads = rows, total, 0, []

    def request_json(self, url, payload=None, method=None):
        self.requests_made += 1
        self.payloads.append(payload)
        start = (payload['current'] - 1) * payload['rowCount']
        return {'rows': self.rows[start:start + payload['rowCount']],
                'total': len(self.rows) if self.total is None else self.total}


class NormalizeTests(unittest.TestCase):
    def test_contact_data_is_never_kept(self):
        job = ajofm.normalize(row(1, description='Sunați la 0747 123 456 sau ion.pop@gmail.com, program L-V.'))
        dump = json.dumps(job, ensure_ascii=False)
        for secret in ('Ion Popescu', '0747000000', 'ion@firma.ro', '0747 123 456', 'ion.pop@gmail.com', 'PARTER'):
            self.assertNotIn(secret, dump)
        self.assertIn('[contact pe ANOFM]', job['description'])
        self.assertIn('program L-V', job['description'])

    def test_text_cleanup(self):
        job = ajofm.normalize(row(2))
        self.assertEqual(job['title'], 'Conducător auto transport rutier de mărfuri')
        self.assertEqual((job['uat'], job['locality']), ('Municipiul Brașov', 'Brașov'))
        self.assertEqual(job['street'], 'Mihail Kogalniceanu 4')
        self.assertEqual(job['cor_code'], '833201')
        self.assertEqual(job['salary_type'], 'brut')
        self.assertEqual(job['source_url'], 'https://mediere.anofm.ro/app/module/mediere/job/2')
        self.assertTrue(job['slug'].startswith('2-conducator-auto'))
        self.assertLessEqual(len(job['slug']), 90)
        self.assertNotIn('--', job['slug'])

    def test_unknown_words_are_not_guessed(self):
        self.assertEqual(ajofm.nice_occupation('OPERATOR LA MASINI-UNELTE CU COMANDA NUMERICA CNC'),
                         'Operator la mașini-unelte cu comandă numerică CNC')
        self.assertEqual(ajofm.nice_occupation('XYZABC'), 'Xyzabc')
        self.assertEqual(ajofm.nice_locality('ORAS VICTORIA'), 'Victoria')
        self.assertEqual(ajofm.nice_locality('SATNOU'), 'Satnou')

    def test_placeholder_salary_is_missing_not_one_leu(self):
        job = ajofm.normalize(row(3, minimum_salary='1.00', maximum_salary='1.00'))
        self.assertIsNone(job['salary_min'])
        self.assertIsNone(job['salary_max'])
        only_max = ajofm.normalize(row(4, minimum_salary=None, maximum_salary='5000'))
        self.assertEqual((only_max['salary_min'], only_max['salary_max']), (5000.0, None))

    def test_rejects_rows_without_basics_or_from_other_counties(self):
        self.assertIsNone(ajofm.normalize(row(None)))
        self.assertIsNone(ajofm.normalize(row(5, occupation='  ')))
        self.assertIsNone(ajofm.normalize(row(6, county_id=29)))


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paginates_until_total(self):
        client = FakeClient([row(i) for i in range(1, 121)])
        payload, stats = ajofm.run(data_dir=self.data, client=client, now=NOW)
        self.assertEqual(client.requests_made, 3)
        self.assertTrue(all(p['county_id'] == 9 for p in client.payloads))
        self.assertEqual(stats['active'], 120)
        stored = json.loads(ajofm.store_path(self.data).read_text(encoding='utf-8'))
        self.assertEqual(len(stored['jobs']), 120)

    def test_incomplete_fetch_keeps_old_data(self):
        ajofm.run(data_dir=self.data, client=FakeClient([row(i) for i in range(1, 11)]), now=NOW)
        before = ajofm.store_path(self.data).read_text(encoding='utf-8')
        with self.assertRaises(FetchError):
            ajofm.run(data_dir=self.data, client=FakeClient([row(1)], total=50), now=NOW)
        with self.assertRaises(FetchError):  # 2 din 10: sub pragul de 40%
            ajofm.run(data_dir=self.data, client=FakeClient([row(1), row(2)]), now=NOW)
        self.assertEqual(ajofm.store_path(self.data).read_text(encoding='utf-8'), before)

    def test_merge_keeps_first_seen_and_retires_vanished_jobs(self):
        ajofm.run(data_dir=self.data, client=FakeClient([row(1), row(2), row(3)]), now=NOW)
        later = NOW + timedelta(hours=12)
        payload, stats = ajofm.run(data_dir=self.data, client=FakeClient([row(1), row(2)]), now=later)
        jobs = payload['jobs']
        self.assertEqual(jobs['1']['first_seen'], NOW.isoformat(timespec='seconds'))
        self.assertEqual(jobs['1']['last_seen'], later.isoformat(timespec='seconds'))
        self.assertFalse(jobs['3']['active'])
        self.assertEqual(stats['new'], 0)
        much_later = NOW + timedelta(days=ajofm.KEEP_INACTIVE_DAYS + 1)
        payload, _ = ajofm.run(data_dir=self.data, client=FakeClient([row(1), row(2)]), now=much_later)
        self.assertNotIn('3', payload['jobs'])

    def test_expired_job_is_inactive(self):
        payload, _ = ajofm.run(data_dir=self.data, now=NOW,
                               client=FakeClient([row(1, job_expiry_date='2026-11-01')]))
        self.assertFalse(payload['jobs']['1']['active'])


class PoliteClientTests(unittest.TestCase):
    def make(self, responses, **kw):
        t = {'now': 0.0}
        slept = []

        def sleep(s):
            slept.append(s)
            t['now'] += s

        client = PoliteClient(sleep=sleep, clock=lambda: t['now'], backoff=1, **kw)
        queue = list(responses)

        def send(req):
            self.assertIn('KronPapirBot', req.get_header('User-agent'))
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        client._send = send
        return client, slept

    def test_two_seconds_between_requests(self):
        client, slept = self.make([(200, b'{"a": 1}'), (200, b'{"a": 2}')])
        self.assertEqual(client.request_json('https://x.test/1', {'p': 1}), {'a': 1})
        self.assertEqual(client.request_json('https://x.test/2', {'p': 2}), {'a': 2})
        self.assertEqual(slept, [2.0])

    def test_retries_then_succeeds(self):
        client, _ = self.make([OSError('reset'), (500, b''), (200, b'{"ok": true}')], retries=3)
        self.assertEqual(client.request_json('https://x.test/'), {'ok': True})
        self.assertEqual(client.requests_made, 3)

    def test_gives_up_after_retries(self):
        client, _ = self.make([OSError('a'), OSError('b')], retries=2)
        with self.assertRaises(FetchError):
            client.request_json('https://x.test/')

    def test_cache_avoids_second_request(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = self.make([(200, b'{"a": 1}')], cache_dir=d)
            client.request_json('https://x.test/', {'q': 1})
            self.assertEqual(client.request_json('https://x.test/', {'q': 1}), {'a': 1})
            self.assertEqual(client.requests_made, 1)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        today = datetime.now(TZ)
        rows = [
            row(10, occupation='CONTABIL', job_domain_name='Financiar', minimum_salary='7000', maximum_salary='9000'),
            row(11, address_locality_name='Brașov > MUNICIPIUL FAGARAS > FAGARAS',
                minimum_salary=None, maximum_salary=None, work_type_name='Cu timp parțial',
                contract_type_name='Cu durată determinată', number_of_months=6),
            row(12, job_expiry_date=(today - timedelta(days=2)).date().isoformat()),
        ]
        ajofm.run(data_dir=cls.tmp.name, client=FakeClient(rows), now=today)
        cls.store = ajofm.store_path(cls.tmp.name)
        webapp.app.config['JOBS_STORE'] = str(cls.store)
        webapp.app.config['TESTING'] = True
        cls.client = webapp.app.test_client()
        cls.jobs = json.loads(cls.store.read_text(encoding='utf-8'))['jobs']

    @classmethod
    def tearDownClass(cls):
        webapp.app.config.pop('JOBS_STORE', None)
        cls.tmp.cleanup()

    def jsonld(self, html):
        return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]

    def test_hub_lists_only_active_jobs(self):
        r = self.client.get('/locuri-de-munca-brasov')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('2 oferte active', html)
        self.assertIn('Contabil', html)
        self.assertNotIn(self.jobs['12']['slug'], html)
        self.assertIn('index, follow', html)
        self.assertNotIn('Ion Popescu', html)
        self.assertNotIn('JobPosting', html)  # Google: JobPosting doar pe pagina ofertei

    def test_hub_shows_market_charts_only_unfiltered(self):
        html = self.client.get('/locuri-de-munca-brasov').get_data(as_text=True)
        self.assertIn('Piața muncii în județul Brașov', html)
        self.assertEqual(html.count('class="kp-chart"'), 3)
        self.assertIn('Posturi pe domenii (AJOFM Brașov)', html)
        filtered = self.client.get('/locuri-de-munca-brasov?domeniu=Financiar').get_data(as_text=True)
        self.assertNotIn('Piața muncii în județul Brașov', filtered)

    def test_hub_filters_are_noindex(self):
        html = self.client.get('/locuri-de-munca-brasov?loc=F%C4%83g%C4%83ra%C8%99').get_data(as_text=True)
        self.assertIn('noindex, follow', html)
        self.assertIn('1 ofertă găsită', html)
        self.assertNotIn('>Contabil<', html)

    def test_detail_has_valid_jobposting_without_contact(self):
        job = self.jobs['10']
        r = self.client.get(f"/locuri-de-munca-brasov/{job['slug']}")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for secret in ('Ion Popescu', '0747000000', 'ion@firma.ro'):
            self.assertNotIn(secret, html)
        blocks = {b['@type']: b for b in self.jsonld(html)}
        jp = blocks['JobPosting']
        for key in ('title', 'description', 'datePosted', 'validThrough', 'hiringOrganization', 'jobLocation'):
            self.assertTrue(jp.get(key), key)
        self.assertEqual(jp['baseSalary']['value']['minValue'], 7000.0)
        self.assertEqual(jp['baseSalary']['currency'], 'RON')
        self.assertEqual(jp['employmentType'], 'FULL_TIME')
        self.assertEqual(jp['validThrough'], '2027-01-24T23:59:59+02:00')
        self.assertIn('mediere.anofm.ro/app/module/mediere/job/10', html)
        self.assertIn('BreadcrumbList', blocks)

    def test_missing_fields_stay_missing(self):
        job = self.jobs['11']
        jp = {b['@type']: b for b in self.jsonld(
            self.client.get(f"/locuri-de-munca-brasov/{job['slug']}").get_data(as_text=True))}['JobPosting']
        self.assertNotIn('baseSalary', jp)
        self.assertEqual(jp['employmentType'], ['PART_TIME', 'TEMPORARY'])
        self.assertEqual(jp['jobLocation']['address']['addressLocality'], 'Făgăraș')

    def test_expired_job_returns_410_without_jobposting(self):
        r = self.client.get(f"/locuri-de-munca-brasov/{self.jobs['12']['slug']}")
        self.assertEqual(r.status_code, 410)
        html = r.get_data(as_text=True)
        self.assertIn('Oferta nu mai este activă', html)
        self.assertNotIn('"JobPosting"', html)
        self.assertIn('noindex', html)

    def test_slug_redirects_and_404s(self):
        r = self.client.get('/locuri-de-munca-brasov/10-alt-titlu')
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r.headers['Location'].endswith(self.jobs['10']['slug']))
        self.assertEqual(self.client.get('/locuri-de-munca-brasov/999-x').status_code, 404)
        self.assertEqual(self.client.get('/locuri-de-munca-brasov/abc').status_code, 404)

    def test_sitemap_has_hub_and_active_jobs_only(self):
        xml = all_sitemaps(self.client)
        self.assertIn('https://kronpapir.ro/locuri-de-munca-brasov</loc>', xml)
        self.assertIn(self.jobs['10']['slug'], xml)
        self.assertNotIn(self.jobs['12']['slug'], xml)

    def test_romanian_counts(self):
        c = jobs_web.ro_count
        self.assertEqual(c(1, 'post', 'posturi'), '1 post')
        self.assertEqual(c(19, 'post', 'posturi'), '19 posturi')
        self.assertEqual(c(20, 'post', 'posturi'), '20 de posturi')
        self.assertEqual(c(105, 'post', 'posturi'), '105 posturi')
        self.assertEqual(c(239, 'post', 'posturi'), '239 de posturi')
        self.assertEqual(c(300, 'post', 'posturi'), '300 de posturi')


if __name__ == '__main__':
    unittest.main()
