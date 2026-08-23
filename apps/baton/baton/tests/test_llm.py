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
        """Uses a purpose no model claims.

        This used to ask for "Summarisation", which was only unclaimed because
        nobody had configured a model for it yet. The moment one existed the
        test failed while the fallback it checks still worked -- the assertion
        was fine, the premise had an expiry date on it.
        """
        claimed = set(frappe.get_all("Baton AI Model", filters={"enabled": 1},
                                     pluck="purpose"))
        unclaimed = next((p for p in ("General", "Qualification", "Conversation",
                                      "Summarisation", "Workflow")
                          if p not in claimed), None)
        if unclaimed is None:
            self.skipTest("every purpose has a model, so there is no fallback to check")
        self.assertEqual(llm.get_model_config(unclaimed).name,
                         llm.get_model_config().name)

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


class TestCredentialTester(FrappeTestCase):
    """Testing a key must not require the kill switch to be off... or on.

    The switch exists to stop Baton acting on customers. Refusing to verify a
    credential until it is on means the only way to find out whether a key works
    is to switch the whole product on and watch -- which is exactly backwards,
    and is what made a freshly configured site untestable.
    """

    def setUp(self):
        self.saved = frappe.db.get_single_value("Baton Settings", "ai_enabled")
        frappe.db.set_single_value("Baton Settings", "ai_enabled", 0)
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")

    def tearDown(self):
        frappe.db.set_single_value("Baton Settings", "ai_enabled", self.saved)
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")

    def test_chat_still_refuses_while_the_switch_is_off(self):
        from baton.llm import LLMNotConfigured, chat

        with self.assertRaises(LLMNotConfigured) as e:
            chat([{"role": "user", "content": "hi"}])
        self.assertIn("switched off", str(e.exception))

    def test_the_tester_reaches_the_provider_anyway(self):
        from unittest.mock import MagicMock, patch

        from baton.llm import ADAPTERS, test_model

        model = _model("T Tester Model")
        # ADAPTERS binds the function at import, so the dict entry is what a
        # stub has to replace.
        adapter = MagicMock(return_value="OK")
        with patch.dict(ADAPTERS, {"OpenAI Compatible": adapter}):
            out = test_model(model.name)
        self.assertTrue(out["ok"], out)
        self.assertEqual(adapter.call_count, 1,
                         "the tester must actually call the provider")

    def test_the_tester_reports_a_bad_key_rather_than_raising(self):
        from unittest.mock import MagicMock, patch

        from baton.llm import ADAPTERS, LLMCallFailed, test_model

        model = _model("T Tester Model")
        adapter = MagicMock(side_effect=LLMCallFailed("401 Unauthorized"))
        with patch.dict(ADAPTERS, {"OpenAI Compatible": adapter}):
            out = test_model(model.name)
        self.assertFalse(out["ok"])
        self.assertIn("401", out["message"])


class TestBrowserCredentials(FrappeTestCase):
    def test_browser_key_overrides_the_stored_key_for_one_request(self):
        from unittest.mock import MagicMock, patch

        model = _model("T Browser Credential")
        adapter = MagicMock(return_value="OK")
        credential = frappe.as_json(
            {
                "model_name": model.name,
                "api_key": "sk-browser-only",
            }
        )

        with patch.dict(llm.ADAPTERS, {"OpenAI Compatible": adapter}):
            with llm.use_client_credential(credential):
                llm.chat(
                    [{"role": "user", "content": "hi"}],
                    allow_while_off=True,
                )

        self.assertEqual(adapter.call_args.args[1], "sk-browser-only")
        self.assertEqual(model.get_password("api_key"), "sk-test")
        self.assertIsNone(llm.client_credential_model())

    def test_model_metadata_endpoint_does_not_store_a_posted_key(self):
        from baton.api.connections import save_model

        name = "T Browser Metadata Only"
        if frappe.db.exists("Baton AI Model", name):
            frappe.delete_doc(
                "Baton AI Model", name, force=True, ignore_permissions=True
            )

        save_model(
            model_name=name,
            api_key="must-not-reach-the-database",
            provider="OpenAI Compatible",
            model="test-model",
            purpose="General",
            enabled=1,
        )
        self.assertFalse(
            frappe.get_doc("Baton AI Model", name).get_password(
                "api_key", raise_exception=False
            )
        )
        frappe.delete_doc(
            "Baton AI Model", name, force=True, ignore_permissions=True
        )
        frappe.db.commit()

    def test_saving_metadata_removes_a_legacy_server_key(self):
        from baton.api.connections import save_model

        model = _model("T Legacy Server Key")
        self.assertEqual(model.get_password("api_key"), "sk-test")

        save_model(
            model_name=model.name,
            provider=model.provider,
            model=model.model,
            purpose=model.purpose,
            enabled=1,
        )

        self.assertFalse(
            frappe.get_doc("Baton AI Model", model.name).get_password(
                "api_key", raise_exception=False
            )
        )


def _model(name):
    if frappe.db.exists("Baton AI Model", name):
        frappe.delete_doc("Baton AI Model", name, force=True, ignore_permissions=True)
    doc = frappe.get_doc({
        "doctype": "Baton AI Model", "model_name": name, "enabled": 1,
        "provider": "OpenAI Compatible", "model": "test-model",
        "api_key": "sk-test", "purpose": "General",
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return doc
