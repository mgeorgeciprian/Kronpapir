"""SEO: indexul de sitemap-uri, sitemap-uri pe categorii, canonical, politica editorială."""
import json
import re
import unittest

import test_editorial_foundation as fnd  # setează env-ul de test înainte de importul aplicației

art = fnd.art
webapp = fnd.webapp


class SeoTests(unittest.TestCase):
    def setUp(self):
        fnd.WebTests.setUp(self)  # același mediu izolat (directoare temporare)

    def write(self, a):
        with open(self.data / f"{a['id']}.json", 'w', encoding='utf-8') as f:
            json.dump(a, f, ensure_ascii=False)

    def test_sitemap_is_index_of_sections(self):
        self.write(art('c1', slug='concert', category='cultura'))
        self.write(art('e1', slug='editorial-1', category='editorial', is_editorial=True))
        self.write(art('r1', slug='rar', category='turism'))
        r = self.client.get('/sitemap.xml')
        self.assertEqual(r.status_code, 200)
        index = r.get_data(as_text=True)
        self.assertIn('<sitemapindex', index)
        for name in ('sitemap-pagini.xml', 'sitemap-stiri-cultura.xml',
                     'sitemap-stiri-editoriale.xml', 'sitemap-stiri-altele.xml', 'news-sitemap.xml'):
            self.assertIn(f'https://kronpapir.ro/{name}</loc>', index)
        # secțiunile fără articole nu apar în index
        self.assertNotIn('sitemap-stiri-sport.xml', index)

        cultura = self.client.get('/sitemap-stiri-cultura.xml').get_data(as_text=True)
        self.assertIn('/stiri/concert</loc>', cultura)
        self.assertNotIn('/stiri/editorial-1', cultura)
        self.assertIn('/stiri/rar</loc>', self.client.get('/sitemap-stiri-altele.xml').get_data(as_text=True))

    def test_every_listed_sitemap_answers_and_unknown_is_404(self):
        self.write(art('l1', slug='stire-locala', source_type='date_oficiale'))
        index = self.client.get('/sitemap.xml').get_data(as_text=True)
        for path in re.findall(r'<loc>https://kronpapir\.ro(/[^<]+)</loc>', index):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn('xml', r.mimetype)
        self.assertEqual(self.client.get('/sitemap-stiri-inexistent.xml').status_code, 404)

    def test_pages_sitemap_lists_policy_page(self):
        xml = self.client.get('/sitemap-pagini.xml').get_data(as_text=True)
        self.assertIn('https://kronpapir.ro/politica-editoriala</loc>', xml)
        self.assertIn('https://kronpapir.ro/categorie/sport</loc>', xml)

    def test_lastmod_prefers_update_date(self):
        self.write(art('u1', slug='actualizat', category='sport', date='2026-10-01T09:00:00',
                       updated='2026-11-20T12:00:00'))
        xml = self.client.get('/sitemap-stiri-sport.xml').get_data(as_text=True)
        self.assertIn('<loc>https://kronpapir.ro/stiri/actualizat</loc><lastmod>2026-11-20</lastmod>', xml)

    def test_group_aliases(self):
        g = webapp._sitemap_group
        self.assertEqual(g({'category': 'culture'}), 'cultura')
        self.assertEqual(g({'category': 'nacional'}), 'national')
        self.assertEqual(g({'category': 'local', 'is_editorial': True}), 'editoriale')
        self.assertEqual(g({'category': 'accidente', 'type': 'national'}), 'national')
        self.assertEqual(g({'category': ''}), 'altele')

    def test_default_canonical_is_the_page_itself(self):
        html = self.client.get('/despre').get_data(as_text=True)
        self.assertIn('<link rel="canonical" href="https://kronpapir.ro/despre">', html)
        self.assertNotIn('hreflang', html)
        html = self.client.get('/categorie/sport?page=2&x=1').get_data(as_text=True)
        self.assertIn('<link rel="canonical" href="https://kronpapir.ro/categorie/sport?page=2">', html)

    def test_editorial_policy_page(self):
        r = self.client.get('/politica-editoriala')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('Politica editorială', html)
        self.assertIn('inteligența artificială', html)
        self.assertIn('Actualizare:', html)
        self.assertIn('href="/politica-editoriala"', self.client.get('/despre').get_data(as_text=True))

    def test_article_jsonld_points_to_policy(self):
        self.write(art('j1', slug='cu-principii', source_type='date_oficiale'))
        html = self.client.get('/stiri/cu-principii').get_data(as_text=True)
        self.assertIn('"publishingPrinciples": "https://kronpapir.ro/politica-editoriala"', html)


if __name__ == '__main__':
    unittest.main()
