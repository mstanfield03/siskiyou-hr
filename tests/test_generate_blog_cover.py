"""Offline checks for paid-call count, CMS requests and concurrent editing."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('cover', Path(__file__).resolve().parents[1] / 'scripts/generate_blog_cover.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
POST = {'title': 'Salary and job duties', 'body': '<h2>The duties test</h2><p>Compare actual work.</p>',
        'excerpt': 'A guide to employee classification.', 'tags': 'salary, duties',
        'published': False, 'cover': '', 'cover_alt': '', 'seo': {'description': 'Existing SEO'}}
IMAGE = b'RIFF' + b'\x10\0\0\0' + b'WEBP' + b'test-data'

def payload():
    return {'source': 'pages-cms', 'action': {'name': m.ACTION},
            'repository': {'owner': 'mstanfield03', 'repo': 'siskiyou-hr', 'ref': 'main', 'sha': 'a' * 40},
            'context': {'type': 'entry', 'name': 'posts', 'path': 'content/posts/test-post.json', 'data': {'title': 'Unsaved title'}},
            'inputs': {}}

class FakeGitHub:
    def __init__(self, post=None, changed=False, move_once=False):
        self.saved_post = copy.deepcopy(post or POST)
        self.changed = changed
        self.move_once = move_once
        self.writes = []
        self.patches = 0
    def post(self, path, ref):
        return copy.deepcopy(self.saved_post), 'changed' if self.changed and ref == 'head' else 'post-blob'
    def head(self): return 'head', 'tree'
    def api(self, method, path, data=None):
        self.writes.append((method, path, copy.deepcopy(data)))
        if method == 'PATCH':
            self.patches += 1
            if self.move_once and self.patches == 1: raise m.RefMoved()
        return {'sha': 'new-object'}

class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.data).encode()

class CoverTests(unittest.TestCase):
    def test_valid_cms_request(self):
        self.assertEqual(m.validate_payload(payload()), ('content/posts/test-post.json', 'a' * 40, False, ''))
    def test_path_branch_and_repository_boundaries(self):
        for key, value in [('path', '../../index.html'), ('path', 'content/posts/../site.json'), ('type', 'collection')]:
            request = payload(); request['context'][key] = value
            with self.assertRaises(m.CoverError): m.validate_payload(request)
        for key, value in [('ref', 'other-branch'), ('sha', 'not-a-sha'), ('owner', 'someone-else')]:
            request = payload(); request['repository'][key] = value
            with self.assertRaises(m.CoverError): m.validate_payload(request)
    def test_checkbox_cannot_be_a_truthy_string(self):
        request = payload(); request['inputs']['replace_existing'] = 'false'
        with self.assertRaises(m.CoverError): m.validate_payload(request)
    def test_prompt_uses_saved_article_and_locked_style(self):
        result = m.build_prompt(POST, 'a work-duty checklist')
        self.assertIn('Salary and job duties', result)
        self.assertIn('Compare actual work.', result)
        self.assertIn('#7A8F7B', result)
        self.assertIn('near-symmetrical', result)
        self.assertNotIn('<h2>', result)
    def test_missing_key_makes_no_request(self):
        with patch.object(m, 'urlopen') as request:
            with self.assertRaisesRegex(m.CoverError, 'OPENAI_API_KEY'): m.generate_image('prompt', '', b'ref')
            request.assert_not_called()
    def test_one_image_request_with_reference(self):
        with patch.object(m, 'urlopen', return_value=Response({'data': [{'b64_json': base64.b64encode(IMAGE).decode()}]})) as request:
            self.assertEqual(m.generate_image('prompt', 'private-test-key', b'ref'), IMAGE)
            self.assertEqual(request.call_count, 1)
            sent = json.loads(request.call_args.args[0].data)
            self.assertEqual(sent['model'], 'gpt-image-2')
            self.assertEqual(sent['n'], 1)
            self.assertEqual(sent['size'], '1536x1024')
            self.assertTrue(sent['images'][0]['image_url'].startswith('data:image/jpeg;base64,'))
    def test_timeout_is_not_retried(self):
        with patch.object(m, 'urlopen', side_effect=TimeoutError) as request:
            with self.assertRaisesRegex(m.CoverError, 'usage'): m.generate_image('prompt', 'key', b'ref')
            self.assertEqual(request.call_count, 1)
    def test_invalid_response_never_reaches_repository(self):
        with patch.object(m, 'urlopen', return_value=Response({'data': [{'b64_json': 'invalid'}]})):
            with self.assertRaises(m.CoverError): m.generate_image('prompt', 'key', b'ref')
    def test_existing_upload_is_protected_before_paid_call(self):
        post = copy.deepcopy(POST); post['cover'] = '/Images/blog/upload.jpg'
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'generate_image') as generate:
            with self.assertRaisesRegex(m.CoverError, 'already has a cover'):
                m.run(payload(), FakeGitHub(post), 'key', Path(temp))
            generate.assert_not_called()
    def test_stale_editor_does_not_spend(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'generate_image') as generate:
            with self.assertRaisesRegex(m.CoverError, 'newer saved changes'):
                m.run(payload(), FakeGitHub(changed=True), 'key', Path(temp))
            generate.assert_not_called()
    def test_atomic_save_preserves_post_and_publication_status(self):
        for published in [False, True]:
            post = copy.deepcopy(POST); post['published'] = published
            gh = FakeGitHub(post)
            path, state = m.commit_cover(gh, 'content/posts/test-post.json', 'post-blob', post, IMAGE)
            self.assertEqual(state, published)
            saved = next(json.loads(data['content']) for method, url, data in gh.writes if url == '/git/blobs' and data['encoding'] == 'utf-8')
            self.assertEqual(saved['published'], published)
            self.assertEqual(saved['body'], POST['body'])
            self.assertEqual(saved['seo'], POST['seo'])
            self.assertEqual(saved['cover'], '/' + path)
            tree = next(data for method, url, data in gh.writes if url == '/git/trees')
            self.assertEqual(len(tree['tree']), 2)
            self.assertFalse(next(data for method, url, data in gh.writes if method == 'PATCH')['force'])
    def test_concurrent_edit_never_moves_ref(self):
        gh = FakeGitHub(changed=True)
        with self.assertRaisesRegex(m.CoverError, 'changed while'): m.commit_cover(gh, 'content/posts/test-post.json', 'post-blob', POST, IMAGE)
        self.assertFalse(any(method == 'PATCH' for method, _, _ in gh.writes))
    def test_unrelated_branch_change_retries_commit_only(self):
        gh = FakeGitHub(move_once=True)
        m.commit_cover(gh, 'content/posts/test-post.json', 'post-blob', POST, IMAGE)
        self.assertEqual(gh.patches, 2)
        self.assertEqual(len([x for x in gh.writes if x[1] == '/git/blobs']), 2)
    def test_draft_save_and_replacement_preserve_all_other_fields(self):
        gh = FakeGitHub(); gh.saved_post['cover'] = '/Images/blog/old.png'
        request = payload(); request['inputs']['replace_existing'] = True
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'generate_image', return_value=IMAGE) as generate:
            m.run(request, gh, 'key', Path(temp))
            self.assertEqual(generate.call_count, 1)
            self.assertTrue((Path(temp) / 'cover.webp').exists())
            self.assertNotIn('Unsaved title', generate.call_args.args[0])
            self.assertFalse(any('/dispatches' in url for _, url, _ in gh.writes))
    def test_published_cover_explicitly_dispatches_deployment(self):
        gh = FakeGitHub(); gh.saved_post['published'] = True
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'generate_image', return_value=IMAGE):
            m.run(payload(), gh, 'key', Path(temp))
        self.assertTrue(any(url == '/actions/workflows/publish.yml/dispatches' for _, url, _ in gh.writes))

if __name__ == '__main__': unittest.main()
