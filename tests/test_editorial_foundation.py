"""Fundația redacției: ciorne, publicare, semnături, noindex, JSON-LD, sitemap, cache.

Run: python -m pytest tests/test_editorial_foundation.py -q
Toate datele stau într-un folder temporar; se setează doar valori false în env.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ['FLASK_SECRET_KEY'] = 'fake-test-secret'
os.environ['ADMIN_PASSWORD'] = 'fake-test-password'
os.environ['PIXABAY_API_KEY'] = ''
os.environ.pop('ANTHROPIC_API_KEY', None)

from editorial import presentation as pres  # noqa: E402
from editorial import store  # noqa: E402
from web import app as webapp  # noqa: E402


def all_sitemaps(client):
    """Textul tuturor sitemap-urilor din indexul /sitemap.xml, lipite."""
    index = client.get('/sitemap.xml').get_data(as_text=True)
    paths = re.findall(r'<loc>https://kronpapir\.ro(/[^<]+)</loc>', index)
    return '\n'.join(client.get(p).get_data(as_text=True) for p in paths)


def art(art_id, **extra):
    base = {'id': art_id, 'title': f'Titlu {art_id}', 'slug': f'slug-{art_id}', 'category': 'local',
            'type': 'local', 'content': '<p>Conținut de test.</p>', 'source': 'Test',
            'date': '2026-11-26T10:00:00'}
    base.update(extra)
    return base


class PresentationTests(unittest.TestCase):
    def test_page_title_strips_duplicate_branding(self):
        a = {'seo_title': 'Tamás Sándor vrea comasarea | Politică | KronPapir.ro', 'title': 'x'}
        self.assertEqual(pres.page_title(a), 'Tamás Sándor vrea comasarea | KronPapir')
        self.assertEqual(pres.page_title({'title': 'Simplu'}), 'Simplu | KronPapir')

    def test_safe_image_blocks_hotlinks_and_pixabay_temp(self):
        self.assertIsNone(pres.safe_image({'image': 'https://brasovstiri.ro/wp-content/x.png'}))
        self.assertIsNone(pres.safe_image({'image': 'https://pixabay.com/get/g74a55.jpg'}))
        self.assertEqual(pres.safe_image({'image': '/static/media/a.webp'}), '/static/media/a.webp')
        self.assertEqual(pres.safe_image({'image': 'https://kronpapir.ro/media/a.webp'}),
                         'https://kronpapir.ro/media/a.webp')
        self.assertEqual(pres.og_image({'image': 'https://g4media.ro/a.webp'}), pres.DEFAULT_OG_IMAGE)

    def test_source_types_and_noindex(self):
        legacy = art('a', url='https://www.brasovstiri.ro/stire')
        self.assertEqual(pres.source_type(legacy), 'rescriere_veche')
        self.assertTrue(pres.should_noindex(legacy))
        reviewed = dict(legacy, reviewed_by='George', reviewed_at='2026-11-26T12:00:00')
        self.assertFalse(pres.should_noindex(reviewed))
        editorial = art('e', is_editorial=True, url='https://kronpapir.ro/stiri/editorial-x')
        self.assertFalse(pres.should_noindex(editorial))
        data = art('d', source_type='date_oficiale', url='https://www.brasovcity.ro/x')
        self.assertFalse(pres.should_noindex(data))

    def test_noindex_switch(self):
        legacy = art('a', url='https://www.brasovstiri.ro/stire')
        with mock.patch.dict(os.environ, {'NOINDEX_REWRITES': 'false'}):
            self.assertFalse(pres.should_noindex(legacy))

    def test_bylines(self):
        data = art('d', source_type='date_oficiale', source='Primăria Brașov',
                   source_url='https://www.brasovcity.ro/primaria/anunt-licitatie/3335')
        b = pres.byline(data)
        self.assertTrue(b['text'].startswith(pres.BYLINE_AUTO_DATA))
        self.assertEqual(b['source_url'], 'https://www.brasovcity.ro/primaria/anunt-licitatie/3335')
        # Eticheta „cu verificare umană” doar cu ambele câmpuri
        self.assertEqual(pres.byline(dict(data, reviewed_by='George'))['text'], b['text'])
        self.assertEqual(pres.byline(dict(data, reviewed_by='George', reviewed_at='2026-11-26'))['text'],
                         pres.BYLINE_REVIEWED)
        legacy = art('a', url='https://litera9.com/x', source='Litera9')
        self.assertTrue(pres.byline(legacy)['text'].startswith(pres.BYLINE_AUTO_PRESS))
        self.assertTrue(pres.byline(art('c', contributor_id='u1', author='Ana Pop'))['person'])

    def test_clean_content_removes_persona_signature(self):
        html = ('<p>Text.</p><p>— Andrei Varga, editorialist KronPapir</p>'
                '<p style="font-style: italic;"><em>— Andrei Varga, editorialist KronPapir</em></p>')
        self.assertEqual(pres.clean_content(html), '<p>Text.</p>')
        self.assertEqual(pres.clean_content('<p>Fără semnătură.</p>'), '<p>Fără semnătură.</p>')

    def test_jsonld_is_valid_and_complete(self):
        a = art('d', source_type='date_oficiale', title='Titlu cu "ghilimele" și </script>',
                location='Brașov', faq=[{'q': 'Până când?', 'a': 'Până pe 8 ianuarie 2027.'}],
                updated='2026-11-27T09:00:00')
        blocks = pres.build_jsonld(a, 'Știri Locale')
        types = [b['@type'] for b in blocks]
        self.assertEqual(types, ['NewsArticle', 'BreadcrumbList', 'FAQPage'])
        news = blocks[0]
        self.assertEqual(news['author'], {'@type': 'Organization', 'name': 'Redacția KronPapir',
                                          'url': 'https://kronpapir.ro'})
        self.assertEqual(news['publisher']['logo']['@type'], 'ImageObject')
        self.assertEqual(news['contentLocation']['name'], 'Brașov')
        self.assertEqual(news['dateModified'], '2026-11-27T09:00:00')
        json.dumps(blocks)  # serializabil
        self.assertEqual(len(pres.build_jsonld(art('x'))), 2)  # fără FAQ inventat


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in {'PROCESSED_DIR': root / 'processed', 'DRAFTS_DIR': root / 'drafts'}.items():
            p = mock.patch.object(store, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.root = root

    def test_draft_publish_cycle(self):
        d = store.save_draft(art('a1'), reason='test')
        self.assertEqual(d['status'], 'draft')
        self.assertTrue((self.root / 'drafts' / 'a1.json').exists())
        self.assertFalse((self.root / 'processed').exists())
        with self.assertRaises(ValueError):
            store.publish_draft('a1', reviewed_by='')
        pub = store.publish_draft('a1', reviewed_by='George')
        self.assertEqual(pub['status'], 'published')
        self.assertEqual(pub['reviewed_by'], 'George')
        self.assertTrue(pub['reviewed_at'])
        self.assertFalse((self.root / 'drafts' / 'a1.json').exists())
        self.assertTrue((self.root / 'processed' / 'a1.json').exists())

    def test_reject(self):
        store.save_draft(art('a2'))
        store.reject_draft('a2', reason='cifre greșite')
        self.assertEqual(store.list_drafts('draft'), [])
        self.assertEqual(store.list_drafts('rejected')[0]['rejection_reason'], 'cifre greșite')

    def test_publish_automatic_rules(self):
        with self.assertRaises(ValueError):
            store.publish_automatic(art('e1', source_type='editorial', fact_check={'scor': 10}))
        with self.assertRaises(ValueError):
            store.publish_automatic(art('d1', source_type='date_oficiale', fact_check={'scor': 7}))
        pub = store.publish_automatic(art('d2', source_type='date_oficiale', fact_check={'scor': 8}))
        self.assertEqual(pub['status'], 'published')
        self.assertEqual(pub['reviewed_by'], '')

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            store.get_draft('../processed/x')


class WebTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.data = root / 'processed'
        self.drafts = root / 'drafts'
        self.data.mkdir()
        contributors = root / 'contributors'
        patches = {
            (webapp, 'DATA_DIR'): self.data,
            (webapp, 'RAW_ARTICLES_DIR'): root / 'articles',
            (webapp, 'ANALYTICS_DIR'): root / 'analytics',
            (webapp, 'CONTACT_DIR'): root / 'contact',
            (webapp, 'CONTRIBUTORS_DIR'): contributors,
            (webapp, 'CONTRIBUTORS_FILE'): contributors / 'users.json',
            (webapp, 'CONTRIBUTOR_ARTICLES_DIR'): contributors / 'articles',
            (store, 'PROCESSED_DIR'): self.data,
            (store, 'DRAFTS_DIR'): self.drafts,
        }
        for (mod, name), value in patches.items():
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        webapp.app.config['TESTING'] = True
        self.client = webapp.app.test_client()

    def write(self, a):
        with open(self.data / f"{a['id']}.json", 'w', encoding='utf-8') as f:
            json.dump(a, f, ensure_ascii=False)

    def login(self):
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

    def test_draft_is_invisible_until_published(self):
        store.save_draft(art('dr1', title='Ciornă secretă', slug='ciorna-secreta'))
        self.assertEqual(self.client.get('/stiri/ciorna-secreta').status_code, 404)
        self.assertNotIn('ciorna-secreta', all_sitemaps(self.client))
        self.assertNotIn('Ciornă secretă', self.client.get('/feed').get_data(as_text=True))
        # neautentificat: fără acces la previzualizare
        self.assertNotEqual(self.client.get('/admin/ciorne/dr1').status_code, 200)

        self.login()
        page = self.client.get('/admin/ciorne/dr1').get_data(as_text=True)
        self.assertIn('Previzualizare ciornă', page)
        self.assertIn('noindex, nofollow', page)
        # fără Origin/Referer: refuzat
        self.assertEqual(self.client.post('/admin/ciorne/dr1/publica').status_code, 403)
        r = self.client.post('/admin/ciorne/dr1/publica', headers={'Origin': 'http://localhost'})
        self.assertEqual(r.status_code, 302)
        page = self.client.get('/stiri/ciorna-secreta').get_data(as_text=True)
        self.assertIn(pres.BYLINE_REVIEWED, page)

    def test_status_draft_in_processed_is_hidden(self):
        self.write(art('x1', slug='scapat', status='draft'))
        self.assertEqual(self.client.get('/stiri/scapat').status_code, 404)

    def test_legacy_rewrite_noindex_and_out_of_sitemaps(self):
        self.write(art('l1', slug='rescriere', url='https://brasovstiri.ro/x',
                       image='https://brasovstiri.ro/poza.jpg'))
        self.write(art('o1', slug='date-oficiale', source_type='date_oficiale',
                       url='https://www.brasovcity.ro/x'))
        page = self.client.get('/stiri/rescriere').get_data(as_text=True)
        self.assertIn('content="noindex, follow"', page)
        self.assertNotIn('brasovstiri.ro/poza.jpg', page)  # fără hotlink
        sitemap = all_sitemaps(self.client)
        self.assertNotIn('/stiri/rescriere', sitemap)
        self.assertIn('/stiri/date-oficiale', sitemap)

    def test_article_head_has_single_tags_and_valid_jsonld(self):
        self.write(art('s1', slug='unic', title='Licitație "test"', source_type='date_oficiale',
                       meta_description='Descriere de test.', faq=[{'q': 'Î?', 'a': 'R.'}]))
        page = self.client.get('/stiri/unic').get_data(as_text=True)
        self.assertEqual(page.count('name="description"'), 1)
        self.assertEqual(page.count('property="og:type"'), 1)
        self.assertEqual(page.count('name="twitter:title"'), 1)
        self.assertIn('<title>Licitație &#34;test&#34; | KronPapir</title>', page)
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
        parsed = [json.loads(b) for b in blocks]
        types = [p.get('@type') for p in parsed]
        for t in ('NewsArticle', 'BreadcrumbList', 'FAQPage'):
            self.assertIn(t, types)

    def test_cache_sees_new_and_edited_files(self):
        self.write(art('c1', slug='cache-unu'))
        self.assertEqual(self.client.get('/stiri/cache-unu').status_code, 200)
        self.write(art('c2', slug='cache-doi'))
        self.assertEqual(self.client.get('/stiri/cache-doi').status_code, 200)
        os.utime(self.data / 'c1.json', ns=(1, 1))  # mtime schimbat -> recitire
        self.write(art('c1', slug='cache-unu', title='Titlu modificat'))
        self.assertIn('Titlu modificat', self.client.get('/stiri/cache-unu').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
