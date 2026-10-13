import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from arxiv_get.__main__ import import_results, load_config, main, prepare
from arxiv_get.ai import Screener, fingerprint, validate_result
from arxiv_get.api import build_query, fetch_papers, parse_feed
from arxiv_get.http import request_bytes
from arxiv_get.render import export_html
from arxiv_get.store import Store


def feed(ids=("2610.00001v1",), total=None):
    entries = ''.join('''<entry><id>http://arxiv.org/abs/{}</id>
        <title>GPU kernel optimization</title><summary>Fused operators for faster inference.</summary>
        <published>2026-10-11T12:00:00Z</published><updated>2026-10-11T12:00:00Z</updated>
        <author><name>Test Author</name></author><category term="cs.LG"/></entry>'''.format(i) for i in ids)
    return ('''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
        <o:totalResults>{}</o:totalResults>{}</feed>'''.format(len(ids) if total is None else total, entries)).encode()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "papers.sqlite3"))
        self.paper = parse_feed(feed())[1][0]
        self.config = load_config(None)
        self.ai = self.config["ai"]
        self.keywords = self.config["keywords"]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_date_query_and_injection(self):
        self.assertEqual(build_query(date(2026, 10, 11), []), "submittedDate:[202610110000 TO 202610112359]")
        self.assertIn("(cat:cs.LG OR cat:cs.PL)", build_query(date(2026, 10, 11), ["cs.LG", "cs.PL"]))
        with self.assertRaises(ValueError):
            build_query(date(2026, 10, 11), ["cs.LG OR all:foo"])

    @patch("arxiv_get.api.request_bytes")
    def test_pagination(self, request):
        request.side_effect = [feed(["2610.00001v1"], 2), feed(["2610.00002v1"], 2)]
        papers = list(fetch_papers(date(2026, 10, 11), date(2026, 10, 11), page_size=1))
        self.assertEqual(len(papers), 2)
        self.assertIn("start=1", request.call_args_list[1].args[0].full_url)

    @patch("arxiv_get.api.request_bytes")
    def test_unexpected_empty_page_is_error(self, request):
        request.return_value = feed([], 2)
        with self.assertRaises(RuntimeError):
            list(fetch_papers(date(2026, 10, 11), date(2026, 10, 11)))

    def test_atom_error(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id><summary>bad query</summary></entry></feed>'
        with self.assertRaisesRegex(ValueError, "bad query"):
            parse_feed(raw)

    def test_explicit_primary_category(self):
        raw = feed().replace(b'</entry>', b'<category term="cs.AR"/><arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.AR"/></entry>')
        paper = parse_feed(raw)[1][0]
        self.assertEqual(paper["categories"], ["cs.LG", "cs.AR"])
        self.assertEqual(paper["primary_category"], "cs.AR")

    def test_version_upsert_and_cache_invalidation(self):
        self.store.save(self.paper)
        key = fingerprint(self.paper, self.keywords, self.ai)
        self.store.save_result(self.paper["id"], key, {"score": 90})
        newer = dict(self.paper, version_id="2610.00001v2", updated="2026-10-12T00:00:00Z")
        self.store.save(newer)
        self.store.save(self.paper)
        self.assertEqual(len(self.store.papers()), 1)
        self.assertEqual(self.store.papers()[0]["version_id"], "2610.00001v2")
        self.assertIsNone(self.store.result(newer["id"], fingerprint(newer, self.keywords, self.ai)))
        self.assertNotEqual(key, fingerprint(self.paper, ["编译器"], self.ai))

    @patch.dict(os.environ, {"ARXIV_AI_API_KEY": "test-only"})
    @patch("arxiv_get.ai.request_bytes")
    def test_ai_request_and_validation(self, request):
        result = {"score": 92, "reason": "通过融合算子减少访存，与算子优化直接相关。", "matched_keywords": ["算子优化"]}
        request.return_value = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}).encode()
        answer = Screener(self.ai, self.keywords).screen(self.paper)
        self.assertEqual(answer["score"], 92)
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("abstract", json.loads(payload["messages"][1]["content"])["paper"])
        request.return_value = b'{"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}'
        with self.assertRaises(ValueError):
            Screener(self.ai, self.keywords).screen(self.paper)

    def test_invalid_ai_scores(self):
        for score in (True, -1, 101, "90", 1.5):
            with self.assertRaises(ValueError):
                validate_result({"score": score, "reason": "理由", "matched_keywords": []}, self.keywords)

    def test_prepare_and_atomic_import(self):
        self.store.save(self.paper)
        pending = Path(self.temp.name) / "pending.json"
        prepare(self.store, [self.paper], self.config, pending)
        task = json.loads(pending.read_text())["papers"][0]
        result = {"id": task["id"], "fingerprint": task["fingerprint"], "score": 93,
                  "reason": "融合算子提升 GPU 性能", "matched_keywords": ["算子优化"]}
        imported = Path(self.temp.name) / "results.json"
        imported.write_text(json.dumps({"results": [result, dict(result, id="unknown")]}))
        with self.assertRaises(ValueError):
            import_results(self.store, [self.paper], self.config, imported)
        self.assertIsNone(self.store.result(self.paper["id"], task["fingerprint"]))
        imported.write_text(json.dumps({"results": [result]}))
        import_results(self.store, [self.paper], self.config, imported)
        self.assertEqual(self.store.result(self.paper["id"], task["fingerprint"])["score"], 93)
        prepare(self.store, [self.paper], self.config, pending)
        self.assertEqual(json.loads(pending.read_text())["papers"], [])

    def test_html_escaping(self):
        paper = dict(self.paper, title="</script><script>alert(1)</script>")
        target = Path(self.temp.name) / "index.html"
        export_html(self.store, [paper], self.keywords, self.ai, target)
        content = target.read_text()
        self.assertNotIn(paper["title"], content)
        self.assertIn("\\u003c/script", content)
        self.assertNotIn("__DATA__", content)

    @patch("arxiv_get.http.time.sleep")
    @patch("arxiv_get.http.urlopen")
    def test_retry_429(self, opener, sleep):
        opener.side_effect = [HTTPError("https://example.test", 429, "limited", {"Retry-After": "3"}, None), io.BytesIO(b"ok")]
        self.assertEqual(request_bytes("https://example.test"), b"ok")
        sleep.assert_called_once_with(3)

    def test_cli_rejects_invalid_dates(self):
        self.assertEqual(main(["fetch", "--start", "2026-10-12", "--end", "2026-10-11"]), 1)

    @patch("arxiv_get.__main__.fetch_papers")
    def test_cli_end_to_end_chat(self, fetch):
        fetch.return_value = iter([self.paper])
        config = dict(self.config, database=str(Path(self.temp.name) / "cli.sqlite3"),
                      output=str(Path(self.temp.name) / "cli.html"))
        cfg_path = Path(self.temp.name) / "config.json"
        cfg_path.write_text(json.dumps(config))
        pending = Path(self.temp.name) / "cli-pending.json"
        self.assertEqual(main(["run", "--config", str(cfg_path), "--date", "2026-10-11", "--file", str(pending)]), 0)
        task = json.loads(pending.read_text())["papers"][0]
        results = Path(self.temp.name) / "cli-results.json"
        results.write_text(json.dumps({"results": [{"id": task["id"], "fingerprint": task["fingerprint"],
            "score": 91, "reason": "测试筛选理由", "matched_keywords": ["算子优化"]}]}))
        self.assertEqual(main(["import-results", "--config", str(cfg_path), "--file", str(results)]), 0)
        html = Path(config["output"]).read_text()
        self.assertIn('"score": 91', html)
        self.assertIn("测试筛选理由", html)


if __name__ == "__main__":
    unittest.main()
