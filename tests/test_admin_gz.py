"""Admin handling of compressed articles (<id>.json.gz) in web/app.py.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_admin_gz -v
All data lives in a temp directory; only fake env values are set.
"""
import gzip
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ['FLASK_SECRET_KEY'] = 'fake-test-secret'
os.environ['ADMIN_PASSWORD'] = 'fake-test-password'
os.environ['PIXABAY_API_KEY'] = ''
os.environ['SMTP_EMAIL'] = ''
os.environ['SMTP_PASSWORD'] = ''
os.environ.pop('ANTHROPIC_API_KEY', None)

from web import app as webapp  # noqa: E402


def article(art_id, title='Titlu', **extra):
    return {'id': art_id, 'title': title, 'category': 'social', 'type': 'local',
            'content': 'Continut de test.', 'source': 'Test',
            'date': '2026-01-01T10:00:00', **extra}


class AdminGzTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.data = root / 'processed'
        self.raw = root / 'articles'
        self.data.mkdir()
        self.raw.mkdir()
        contributors = root / 'contributors'
        for name, value in {
            'DATA_DIR': self.data,
            'RAW_ARTICLES_DIR': self.raw,
            'ANALYTICS_DIR': root / 'analytics',
            'CONTACT_DIR': root / 'contact',
            'CONTRIBUTORS_DIR': contributors,
            'CONTRIBUTORS_FILE': contributors / 'users.json',
            'CONTRIBUTOR_ARTICLES_DIR': contributors / 'articles',
        }.items():
            patcher = mock.patch.object(webapp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        webapp.app.config['TESTING'] = True
        self.client = webapp.app.test_client()
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

    def write_json(self, stem, data):
        path = self.data / f'{stem}.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def write_gz(self, stem, data):
        path = self.data / f'{stem}.json.gz'
        with gzip.open(path, 'wb') as f:
            f.write(json.dumps(data).encode('utf-8'))
        return path

    def titles(self):
        return [a['title'] for a in webapp.load_articles(all_types=True)]

    def edit_form(self, title='Editat'):
        return {'title': title, 'category': 'social', 'type': 'local',
                'content': 'Continut nou.', 'source': 'Test'}


class LoadArticlesTests(AdminGzTestCase):
    def test_gz_only_is_loaded(self):
        self.write_gz('a', article('a', 'Arhivat'))
        self.assertEqual(self.titles(), ['Arhivat'])

    def test_both_forms_appear_once_and_json_wins(self):
        self.write_json('a', article('a', 'Din json'))
        self.write_gz('a', article('a', 'Din gz'))
        self.assertEqual(self.titles(), ['Din json'])

    def test_same_inner_id_under_other_filename_appears_once(self):
        self.write_json('uuid-1', article('uuid-1', 'Din json'))
        self.write_gz('raw-1', article('uuid-1', 'Din gz'))
        self.assertEqual(self.titles(), ['Din json'])

    def test_different_articles_are_all_kept(self):
        self.write_json('a', article('a', 'A'))
        self.write_gz('b', article('b', 'B'))
        self.write_gz('c', [article('c1', 'C1'), article('c2', 'C2')])
        self.assertCountEqual(self.titles(), ['A', 'B', 'C1', 'C2'])


class DeleteTests(AdminGzTestCase):
    def delete(self, art_id):
        return self.client.post(f'/admin/articol/sterge/{art_id}')

    def test_gz_only(self):
        gz = self.write_gz('a', article('a'))
        self.assertEqual(self.delete('a').status_code, 200)
        self.assertFalse(gz.exists())

    def test_json_only(self):
        path = self.write_json('a', article('a'))
        self.assertEqual(self.delete('a').status_code, 200)
        self.assertFalse(path.exists())

    def test_both_forms(self):
        path = self.write_json('a', article('a'))
        gz = self.write_gz('a', article('a'))
        self.assertEqual(self.delete('a').status_code, 200)
        self.assertFalse(path.exists())
        self.assertFalse(gz.exists())
        self.assertEqual(self.titles(), [])

    def test_gz_whose_filename_differs_from_its_id(self):
        gz = self.write_gz('raw-1', article('uuid-1'))
        self.assertEqual(self.delete('uuid-1').status_code, 200)
        self.assertFalse(gz.exists())

    def test_stale_gz_under_other_filename_does_not_come_back(self):
        self.write_json('uuid-1', article('uuid-1', 'Nou'))
        self.write_gz('raw-1', article('uuid-1', 'Vechi'))
        self.assertEqual(self.delete('uuid-1').status_code, 200)
        self.assertEqual(self.titles(), [])

    def test_missing_is_404_and_others_untouched(self):
        other = self.write_gz('b', article('b'))
        self.assertEqual(self.delete('a').status_code, 404)
        self.assertTrue(other.exists())

    def test_requires_login(self):
        gz = self.write_gz('a', article('a'))
        with self.client.session_transaction() as sess:
            sess.clear()
        self.assertEqual(self.delete('a').status_code, 302)
        self.assertTrue(gz.exists())


class EditTests(AdminGzTestCase):
    def edit(self, art_id, form):
        return self.client.post(f'/admin/articol/editeaza/{art_id}', data=form)

    def test_save_replaces_gz_with_json(self):
        gz = self.write_gz('a', article('a', 'Vechi'))
        self.assertEqual(self.edit('a', self.edit_form()).status_code, 200)
        self.assertFalse(gz.exists())
        saved = json.loads((self.data / 'a.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['title'], 'Editat')
        self.assertEqual(self.titles(), ['Editat'])

    def test_save_keeps_existing_filename(self):
        gz = self.write_gz('raw-1', article('uuid-1', 'Vechi'))
        self.edit('uuid-1', self.edit_form())
        self.assertFalse(gz.exists())
        self.assertEqual([p.name for p in self.data.iterdir()], ['raw-1.json'])
        self.assertEqual(self.titles(), ['Editat'])

    def test_invalid_form_keeps_gz(self):
        gz = self.write_gz('a', article('a', 'Vechi'))
        self.edit('a', self.edit_form(title=''))
        self.assertTrue(gz.exists())
        self.assertFalse((self.data / 'a.json').exists())

    def test_failed_write_keeps_gz(self):
        gz = self.write_gz('a', article('a', 'Vechi'))
        with mock.patch.object(webapp.json, 'dump', side_effect=OSError('disk full')):
            self.edit('a', self.edit_form())
        self.assertTrue(gz.exists())


class ProcessedCheckTests(AdminGzTestCase):
    def write_raw(self, art_id):
        source = self.raw / 'sursa'
        source.mkdir(exist_ok=True)
        (source / f'{art_id}.json').write_text(
            json.dumps(article(art_id, 'Brut')), encoding='utf-8')

    def test_is_processed_sees_both_forms(self):
        for art_id in ('gz', 'js', 'none'):
            self.write_raw(art_id)
        self.write_gz('gz', article('gz'))
        self.write_json('js', article('js'))
        flags = {a['id']: a['is_processed'] for a in webapp.load_raw_articles()}
        self.assertEqual(flags, {'gz': True, 'js': True, 'none': False})

    def test_process_skips_compressed_article(self):
        self.write_raw('a')
        gz = self.write_gz('a', article('a', 'Arhivat'))
        response = self.client.post('/admin/process', data={'article_ids[]': ['a']})
        self.assertEqual(response.status_code, 302)
        self.assertFalse((self.data / 'a.json').exists())
        self.assertTrue(gz.exists())

    def test_process_still_handles_new_article(self):
        self.write_raw('a')
        self.client.post('/admin/process', data={'article_ids[]': ['a']})
        self.assertTrue((self.data / 'a.json').exists())


class CompareAndReprocessTests(AdminGzTestCase):
    def fake_rewriter(self, result):
        module = types.ModuleType('ai.rewriter')
        module.ArticleRewriter = mock.Mock(return_value=mock.Mock(
            rewrite_article=mock.Mock(return_value=result)))
        for patcher in (mock.patch.dict(sys.modules, {'ai.rewriter': module}),
                        mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fake-key'})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_raw(self, art_id):
        source = self.raw / 'sursa'
        source.mkdir(exist_ok=True)
        (source / f'{art_id}.json').write_text(
            json.dumps(article(art_id, 'Brut')), encoding='utf-8')

    def test_compare_finds_gz_and_links_clean_filename(self):
        self.write_gz('a', article('a', 'Arhivat'))
        response = self.client.get('/admin/articol/compara/a')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Arhivat', body)
        self.assertIn('/admin/articol/reprocess/a"', body)

    def test_compare_finds_gz_by_inner_id(self):
        self.write_gz('raw-1', article('uuid-1', 'Arhivat'))
        response = self.client.get('/admin/articol/compara/uuid-1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/admin/articol/reprocess/raw-1"', response.get_data(as_text=True))

    def test_compare_prefers_json(self):
        self.write_json('a', article('a', 'Din json'))
        self.write_gz('a', article('a', 'Din gz'))
        body = self.client.get('/admin/articol/compara/a').get_data(as_text=True)
        self.assertIn('Din json', body)
        self.assertNotIn('Din gz', body)

    def test_compare_missing_is_404(self):
        self.assertEqual(self.client.get('/admin/articol/compara/a').status_code, 404)

    def test_reprocess_gz_replaces_it_with_json(self):
        self.write_raw('a')
        gz = self.write_gz('a', article('a', 'Arhivat'))
        self.fake_rewriter(article('nou', 'Rescris'))
        response = self.client.post('/admin/articol/reprocess/a')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertFalse(gz.exists())
        self.assertEqual(self.titles(), ['Rescris'])

    def test_reprocess_failure_keeps_gz(self):
        self.write_raw('a')
        gz = self.write_gz('a', article('a', 'Arhivat'))
        self.fake_rewriter(None)
        self.assertEqual(self.client.post('/admin/articol/reprocess/a').status_code, 500)
        self.assertTrue(gz.exists())
        self.assertFalse((self.data / 'a.json').exists())

    def test_reprocess_missing_is_404(self):
        self.assertEqual(self.client.post('/admin/articol/reprocess/a').status_code, 404)


class ContributorApproveTests(AdminGzTestCase):
    def test_reapproval_removes_stale_gz(self):
        submitted = article('a', 'Colaborator', contributor_id='c1', contributor_name='Test')
        gz = self.write_gz('a', article('a', 'Vechi'))
        with mock.patch.object(webapp, 'load_all_contributor_articles', return_value=[submitted]), \
                mock.patch.object(webapp, 'save_contributor_article'), \
                mock.patch.object(webapp, 'update_contributor_article_count'):
            response = self.client.post('/admin/colaborator/aproba/a')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(gz.exists())
        self.assertEqual(self.titles(), ['Colaborator'])


if __name__ == '__main__':
    unittest.main()
