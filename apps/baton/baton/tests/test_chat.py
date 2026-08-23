from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from baton.api.chat import _validate, ask


class TestChatWithoutQuery(FrappeTestCase):
    def test_null_doctype_is_a_valid_non_query_answer(self):
        self.assertEqual(
            _validate({"doctype": None, "explanation": "Hello!"}),
            (None, [], {}, None, 0),
        )

    def test_greeting_returns_an_answer_instead_of_validation_error(self):
        with patch(
            "baton.api.chat.chat_json",
            return_value={"doctype": None, "explanation": "Hi! Ask me about your CRM."},
        ):
            result = ask("hi")

        self.assertEqual(result["answer"], "Hi! Ask me about your CRM.")
        self.assertIsNone(result["doctype"])
        self.assertEqual(result["rows"], [])
