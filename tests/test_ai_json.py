"""JSON handling in ai/rewriter.py and ai/editorial.py. Claude is faked.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest tests.test_ai_json -v
"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai import rewriter as rw  # noqa: E402
from ai import editorial as ed  # noqa: E402

GOOD = {'title': 'Titlu', 'seo_title': 'Titlu | KronPapir.ro',
        'content': '<p>Text cu <a href="https://x.ro">link</a> si "citat".</p>',
        'meta_description': 'd' * 155, 'slug': 'titlu', 'keywords': ['a', 'b']}


def reply(text, stop='end_turn', thinking=False):
    blocks = [types.SimpleNamespace(type='text', text=text)]
    if thinking:
        blocks.insert(0, types.SimpleNamespace(type='thinking', thinking=''))
    return types.SimpleNamespace(stop_reason=stop, content=blocks)


def make(cls, *replies):
    obj = cls.__new__(cls)
    obj.model, obj.rate_limit_delay, obj.last_api_call = 'm', 0, 0
    obj.client = mock.MagicMock()
    obj.client.messages.create.side_effect = list(replies)
    return obj


class RewriterJson(unittest.TestCase):
    def test_broken_quote_no_longer_saves_truncated_content(self):
        bad = '{"title": "T", "content": "<p>inceput "citat" sfarsit</p>", "slug": "s"}'
        self.assertIsNone(make(rw.ArticleRewriter)._parse_json_response(bad))

    def test_valid_json_with_html_quotes(self):
        r = make(rw.ArticleRewriter, reply(json.dumps(GOOD)))
        self.assertEqual(r._request_json('p', rw.EDITORIAL_SCHEMA)['content'], GOOD['content'])
        fmt = r.client.messages.create.call_args.kwargs['output_config']['format']
        self.assertEqual((fmt['type'], fmt['schema']), ('json_schema', rw.EDITORIAL_SCHEMA))

    def test_thinking_block_first_is_skipped(self):
        r = make(rw.ArticleRewriter, reply(json.dumps(GOOD), thinking=True))
        self.assertEqual(r._request_json('p', rw.EDITORIAL_SCHEMA)['title'], 'Titlu')

    def test_cut_off_answer_is_retried(self):
        r = make(rw.ArticleRewriter, reply('{"title":', stop='max_tokens'), reply(json.dumps(GOOD)))
        self.assertEqual(r._request_json('p', rw.EDITORIAL_SCHEMA)['title'], 'Titlu')
        self.assertEqual(r.client.messages.create.call_count, 2)

    def test_gives_up_after_two_cut_off_answers(self):
        r = make(rw.ArticleRewriter, reply('{', stop='max_tokens'), reply('{', stop='max_tokens'))
        self.assertIsNone(r._request_json('p', rw.EDITORIAL_SCHEMA))

    def test_write_editorial_end_to_end(self):
        r = make(rw.ArticleRewriter, reply(json.dumps(GOOD)))
        arts = [{'title': f'Stire {i}', 'content': 'text', 'source': 'S', 'url': f'u{i}'} for i in range(5)]
        result = r.write_editorial(arts, 'national')
        self.assertEqual(result['content'], GOOD['content'])
        self.assertTrue(result['is_editorial'])

    def test_article_schema_requires_all_fields(self):
        self.assertEqual(set(rw.ARTICLE_SCHEMA['required']), set(rw.ARTICLE_SCHEMA['properties']))
        self.assertIn('category', rw.ARTICLE_SCHEMA['required'])


class EditorialAgentJson(unittest.TestCase):
    cls = next(v for k, v in vars(ed).items() if k == 'EditorialAgent')

    def test_call_claude_uses_schema(self):
        a = make(self.cls, reply(json.dumps(GOOD)))
        self.assertEqual(a._call_claude('p')['slug'], 'titlu')
        kw = a.client.messages.create.call_args.kwargs
        self.assertEqual(kw['max_tokens'], 8192)
        self.assertEqual(kw['output_config']['format']['schema'], ed.EDITORIAL_SCHEMA)

    def test_retry_after_bad_json(self):
        a = make(self.cls, reply('nu e json'), reply(json.dumps(GOOD)))
        self.assertEqual(a._call_claude('p')['title'], 'Titlu')

    def test_none_after_two_failures(self):
        a = make(self.cls, reply('x'), reply('{', stop='max_tokens'))
        self.assertIsNone(a._call_claude('p'))

    def test_api_error_returns_none(self):
        a = make(self.cls)
        a.client.messages.create.side_effect = RuntimeError('boom')
        self.assertIsNone(a._call_claude('p'))


if __name__ == '__main__':
    unittest.main()
