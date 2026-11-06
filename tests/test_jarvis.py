"""Offline tests: ServiceNow and the LLM are faked, seed data is used as the knowledge base."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis.agent import HEADER, build_prompt
from jarvis.main import handle
from jarvis.snow import keywords, rank

SEED = Path(__file__).parent.parent / "seed"
KB = [{"number": f"KB00100{i:02}", **a} for i, a in enumerate(json.loads((SEED / "kb_articles.json").read_text(encoding="utf-8")))]
INCIDENTS = json.loads((SEED / "incidents.json").read_text(encoding="utf-8"))
RESOLVED = [{"number": f"INC00100{i:02}", **r} for i, r in enumerate(INCIDENTS["resolved"])]


class FakeSnow:
    """Same ranking as the real client, over local seed data instead of the Table API."""
    def __init__(self):
        self.notes, self.fields = {}, {}

    def search_kb(self, text):
        return rank(KB, keywords(text), ["short_description", "text"])

    def similar_resolved(self, text):
        return rank(RESOLVED, keywords(text), ["short_description", "description"])

    def triage_options(self):
        return {"network": "Network", "inquiry": "Inquiry"}, {"Network": "gid-net", "Service Desk": "gid-sd"}

    def add_work_note(self, sys_id, note, fields=None):
        self.notes[sys_id], self.fields[sys_id] = note, fields or {}


class FakeLLM:
    def __init__(self, triage_json='{"category": "Network", "assignment_group": "Network"}'):
        self.prompts, self.triage_json = [], triage_json
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, response_format=None):
        self.prompts.append(messages[1]["content"])
        content = self.triage_json if response_format else "Probable cause: test"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class TestJarvis(unittest.TestCase):
    def test_retrieval_finds_right_article_for_each_open_ticket(self):
        expected = ["VPN", "Outlook", "Wi-Fi", "shared folder", "Excel"]
        for inc, word in zip(INCIDENTS["open"], expected):
            top = FakeSnow().search_kb(f"{inc['short_description']} {inc['description']}")
            self.assertIn(word, top[0]["short_description"], inc["short_description"])

    def test_handle_posts_note_built_from_kb(self):
        snow, llm = FakeSnow(), FakeLLM()
        inc = {"sys_id": "abc", "number": "INC0099999", **INCIDENTS["open"][0]}
        handle(inc, snow, llm, "test-model")
        self.assertTrue(snow.notes["abc"].startswith(HEADER))
        self.assertIn("error 809", llm.prompts[0])          # ticket text in prompt
        self.assertIn("vpn-ssl.corp.local", llm.prompts[0])  # KB / resolved ticket content in prompt
        self.assertNotIn("<li>", llm.prompts[0])             # HTML stripped

    def test_prompt_without_knowledge(self):
        p = build_prompt({"number": "INC1", "short_description": "nothing"}, [], [])
        self.assertIn("No KB article", p)

    def test_rank_drops_non_matching(self):
        self.assertEqual(rank([{"t": "abc"}], ["zzz"], ["t"]), [])

    def run_triage(self, triage_json, **incident_fields):
        snow = FakeSnow()
        inc = {"sys_id": "abc", "number": "INC1", "category": "inquiry", "assignment_group": "", **INCIDENTS["open"][2], **incident_fields}
        handle(inc, snow, FakeLLM(triage_json), "test-model")
        return snow.fields["abc"], snow.notes["abc"]

    def test_triage_fills_empty_fields(self):
        fields, note = self.run_triage('{"category": "Network", "assignment_group": "Network"}')
        self.assertEqual(fields, {"category": "network", "assignment_group": "gid-net"})
        self.assertIn("Triage: category Network (set), assignment group Network (set)", note)

    def test_triage_never_overwrites_agent_choices(self):
        fields, note = self.run_triage('{"category": "network", "assignment_group": "Network"}',
                                       category="hardware", assignment_group={"value": "gid-hw"})
        self.assertEqual(fields, {})
        self.assertIn("assignment group Network (suggested, already filled)", note)

    def test_triage_drops_invented_or_broken_output(self):
        for bad in ['{"category": "Plumbing", "assignment_group": "Ghostbusters"}', "not json", "[1]",
                    '{"category": 5, "assignment_group": ["Network"]}']:
            fields, note = self.run_triage(bad)
            self.assertEqual(fields, {}, bad)
            self.assertNotIn("Triage:", note)
            self.assertTrue(note.startswith(HEADER))  # resolution note still posted


if __name__ == "__main__":
    unittest.main()
