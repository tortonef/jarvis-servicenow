"""Docs as code: validation, safe loading, chunking, HTML and publishing. No network, no database."""
import io
import tarfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jarvis.knowledge import check, chunks, load_dir, load_tarball, parse, publish, to_html

ROOT = Path(__file__).parent.parent / "knowledge"
GOOD = """---
id: KB-NET-901
title: Test article
audience: [end-user]
systems: [vpn]
symptoms: ["vpn down"]
owner: network-team
review_by: 2027-01-01
---

## Resolution
1. Step one with `cmd <x>`
   continued line
2. **Bold** and *italic*
"""


def doc(text=GOOD, path="articles/test.md"):
    return parse(path, text)


class TestKnowledge(unittest.TestCase):
    def test_repository_documents_are_valid(self):
        docs = load_dir(ROOT)
        self.assertGreaterEqual(len(docs), 25)
        self.assertEqual(check(docs), [])

    def test_check_reports_each_problem(self):
        missing = doc(GOOD.replace("owner: network-team\n", ""))
        wrong_prefix = doc(GOOD.replace("KB-NET-901", "RB-NET-901"))
        no_section = doc(GOOD.replace("## Resolution", "Resolution"))
        errors = "\n".join(check([doc(), doc(path="articles/copy.md"), missing, wrong_prefix, no_section,
                                  doc(path="misc/x.md")]))
        for expected in ("already used by", "'owner' missing", "must look like KB-AREA-001",
                         "at least one '## ' section", "must live in articles/ or runbooks/"):
            self.assertIn(expected, errors)

    def test_malformed_front_matter_is_a_clear_error(self):
        for bad in ("no front matter", "---\ntitle: a: b\n---\n## x", "---\n- just a list\n---\n## x"):
            with self.assertRaises(ValueError):
                parse("articles/bad.md", bad)

    def test_tarball_reads_only_knowledge_docs_in_memory(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, text in [("repo-sha/knowledge/articles/a.md", GOOD), ("repo-sha/README.md", "x"),
                               ("repo-sha/knowledge/../../etc/passwd.md", GOOD), ("../evil/knowledge/articles/b.md", GOOD)]:
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        docs = load_tarball(buf.getvalue())
        self.assertEqual([d["path"] for d in docs], ["articles/a.md"])

    def test_chunks_and_html(self):
        d = doc()
        self.assertEqual(chunks(d)[0], "Test article\nSymptoms: vpn down")
        self.assertEqual(len(chunks(d)), 2)
        html = to_html(d)
        self.assertIn("<ol><li>Step one with <code>cmd &lt;x&gt;</code><br>continued line</li>", html)
        self.assertIn("<strong>Bold</strong> and <em>italic</em>", html)
        self.assertNotIn("<x>", html)  # Markdown text never becomes live HTML
        self.assertIn("Source: KB-NET-901", html)

    def test_publish_creates_and_retires_through_the_kb_api(self):
        posts = []
        def post(url, json, timeout):
            posts.append(json)
            return mock.Mock(json=lambda: {"result": {"number": "KB0010099"}})
        snow = SimpleNamespace(instance="https://dev1", http=SimpleNamespace(post=post),
                               first=lambda table, q: {"operation_uri": "/api/1/jarvis_kb/articles"})
        kb = mock.Mock()
        publish(snow, kb, [doc()], ["KB-OLD-001"], "Helios Group IT")
        self.assertEqual(posts[0]["doc_id"], "KB-NET-901")
        self.assertEqual(posts[0]["kb"], "Helios Group IT")
        self.assertEqual(posts[1], {"doc_id": "KB-OLD-001", "kb": "Helios Group IT", "retire": True})
        kb.set_kb_number.assert_called_once_with("KB-NET-901", "KB0010099")


if __name__ == "__main__":
    unittest.main()
