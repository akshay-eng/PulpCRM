"""LLM layer tests.

No network: provider dispatch and JSON handling are tested against stubs, so the
suite runs offline and does not spend quota.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton import llm


class TestExtractJson(FrappeTestCase):
    def test_plain(self):
        self.assertEqual(llm.extract_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(llm.extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_wrapped(self):
        self.assertEqual(llm.extract_json('Sure!\n{"a": 1}\nHope that helps.'), {"a": 1})

    def test_trailing_comma_is_repaired(self):
        self.assertEqual(llm.extract_json('{"a": 1, "b": [1, 2,],}'), {"a": 1, "b": [1, 2]})

    def test_garbage_raises(self):
        with self.assertRaises(llm.LLMCallFailed):
            llm.extract_json("no json here at all")


class TestChatJsonRetry(FrappeTestCase):
    """Models corrupt their own JSON. Observed on gemini-2.5-flash at
    temperature 0: 2 of 5 identical calls returned a stray token spliced into a
    string array. Retry is the fix; better parsing is not."""

    def test_recovers_after_one_corrupt_response(self):
        corrupt = '{\n "doctype": "CRM Deal",\n "fields": [\n "name"\n  fairness",\n ],\n}'
        good = '{"doctype": "CRM Deal", "fields": ["name"], "limit": 3}'
        with patch.object(llm, "chat", side_effect=[corrupt, good]) as m:
            out = llm.chat_json([{"role": "user", "content": "x"}])
        self.assertEqual(out["doctype"], "CRM Deal")
        self.assertEqual(m.call_count, 2)

    def test_gives_up_after_configured_attempts(self):
        with patch.object(llm, "chat", return_value="not json"):
            with self.assertRaises(llm.LLMCallFailed):
                llm.chat_json([{"role": "user", "content": "x"}], attempts=2)

    def test_retry_shows_the_model_its_own_bad_output(self):
        """Self-correction depends on the model seeing what it got wrong."""
        captured = []

        def fake_chat(messages, **kw):
            captured.append(messages)
            return '{"ok": true}' if len(captured) > 1 else "broken{"

        with patch.object(llm, "chat", side_effect=fake_chat):
            llm.chat_json([{"role": "user", "content": "x"}])

        self.assertEqual(len(captured), 2)
        second = captured[1]
        self.assertEqual(second[-2]["role"], "assistant")
        self.assertIn("broken{", second[-2]["content"])
        self.assertIn("not valid JSON", second[-1]["content"])


class TestProviderDispatch(FrappeTestCase):
    def test_all_five_providers_registered(self):
        self.assertEqual(
            set(llm.ADAPTERS),
            {"OpenAI Compatible", "Anthropic", "Google Gemini", "Ollama", "Azure OpenAI"},
        )

    def test_only_ollama_is_keyless(self):
        self.assertEqual(llm.KEYLESS, {"Ollama"})

    def test_default_model_resolves(self):
        cfg = llm.get_model_config()
        self.assertTrue(cfg.is_default)
        self.assertTrue(cfg.enabled)

    def test_unknown_purpose_falls_back_to_default(self):
        fallback = llm.get_model_config("Summarisation")
        self.assertEqual(fallback.name, llm.get_model_config().name)

    def test_global_switch_blocks_calls(self):
        original = frappe.db.get_single_value("Baton Settings", "ai_enabled")
        try:
            frappe.db.set_single_value("Baton Settings", "ai_enabled", 0)
            frappe.clear_cache(doctype="Baton Settings")
            with self.assertRaises(llm.LLMNotConfigured):
                llm.chat([{"role": "user", "content": "x"}])
        finally:
            frappe.db.set_single_value("Baton Settings", "ai_enabled", original)
            frappe.clear_cache(doctype="Baton Settings")
