"""Offline tests: ServiceNow and the LLM are faked, seed data is used as the knowledge base."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis.agent import HEADER, build_prompt
from jarvis.main import handle, handle_resolved
from jarvis.snow import keywords, rank

SEED = Path(__file__).parent.parent / "seed"
KB = [{"number": f"KB00100{i:02}", **a} for i, a in enumerate(json.loads((SEED / "kb_articles.json").read_text(encoding="utf-8")))]
INCIDENTS = json.loads((SEED / "incidents.json").read_text(encoding="utf-8"))
RESOLVED = [{"number": f"INC00100{i:02}", **r} for i, r in enumerate(INCIDENTS["resolved"])]


class FakeSnow:
    """Same ranking as the real client, over local seed data instead of the Table API."""
    def __init__(self, existing_draft=None):
        self.notes, self.fields, self.created, self.existing_draft = {}, {}, [], existing_draft

    def kb_candidates(self, text):
        return self.search_kb(text)

    def draft_for(self, sys_id):
        return self.existing_draft

    def kb_base(self, title):
        return {"sys_id": "kb-demo"}

    def create(self, table, data):
        self.created.append((table, data))
        return {"number": "KB0099999", **data}

    def search_kb(self, text):
        return rank(KB, keywords(text), ["short_description", "text"])

    def similar_resolved(self, text):
        return rank(RESOLVED, keywords(text), ["short_description", "description"])

    def triage_options(self):
        return {"network": "Network", "inquiry": "Inquiry"}, {"Network": "gid-net", "Service Desk": "gid-sd"}

    def add_work_note(self, sys_id, note, fields=None):
        self.notes[sys_id], self.fields[sys_id] = note, fields or {}


class FakeLLM:
    def __init__(self, json_reply='{"category": "Network", "assignment_group": "Network"}'):
        self.prompts, self.json_reply = [], json_reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, temperature, response_format=None):
        self.prompts.append(messages[1]["content"])
        content = self.json_reply if response_format else "Probable cause: test"
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

    def run_resolved(self, json_reply, snow=None, **incident_fields):
        snow, llm = snow or FakeSnow(), FakeLLM(json_reply)
        inc = {"sys_id": "abc", "number": "INC2", "short_description": "Zoom screen sharing shows a black screen",
               "description": "Participants only see black when I share.", "close_notes": "Disabled hardware acceleration.",
               **incident_fields}
        handle_resolved(inc, snow, llm, "test-model")
        return snow, llm

    def test_kb_draft_created_escaped_and_linked(self):
        reply = json.dumps({"covered_by": None, "title": "Zoom: black screen <script>x</script>", "symptom": "Black share",
                            "cause": "GPU acceleration", "steps": ["Open Zoom settings", "Disable <b>hardware</b> acceleration"]})
        snow, llm = self.run_resolved(reply)
        (table, art), = snow.created
        self.assertEqual((table, art["source"], art["kb_knowledge_base"]), ("kb_knowledge", "abc", "kb-demo"))
        self.assertIn("&lt;b&gt;hardware&lt;/b&gt;", art["text"])   # model output escaped in article HTML
        self.assertNotIn("<b>", art["text"])
        self.assertIn("Drafted knowledge article KB0099999", snow.notes["abc"])
        self.assertIn("Disabled hardware acceleration", llm.prompts[0])  # resolution notes reach the model

    def test_kb_draft_skips_covered_fix(self):
        snow = FakeSnow()
        covered = snow.kb_candidates("Teams microphone meetings")[0]["number"]
        snow, _ = self.run_resolved(json.dumps({"covered_by": covered}), snow=snow,
                                    short_description="Teams: nobody can hear me in meetings")
        self.assertEqual(snow.created, [])
        self.assertIn(f"already documented in {covered}", snow.notes["abc"])

    def test_kb_draft_rejects_bad_output_and_skips_needless_calls(self):
        for bad in ['{"covered_by": "KB0000000"}', '{"covered_by": ["x"]}', '{"title": "x", "steps": []}', "nope",
                    '{"title": "", "steps": ["a"]}', '{"title": "t", "steps": [1, 2]}']:
            snow, _ = self.run_resolved(bad)
            self.assertEqual((snow.created, snow.notes), ([], {}), bad)
        for snow, fields in ((FakeSnow(existing_draft={"number": "KB1"}), {}), (FakeSnow(), {"close_notes": " "})):
            _, llm = self.run_resolved("{}", snow=snow, **fields)
            self.assertEqual(llm.prompts, [])  # no LLM call when there is nothing to do


if __name__ == "__main__":
    unittest.main()
