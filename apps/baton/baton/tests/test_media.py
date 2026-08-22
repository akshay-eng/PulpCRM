"""Inbound WhatsApp media.

OpenWA sheds media blobs from webhook payloads over a size cap and sends a
marker instead:

    "media": {"mimetype": "image/jpeg", "omitted": true, "sizeBytes": 195683}

so the bytes must be fetched separately. Observed live: an image arrived as an
empty bubble because the payload carried no body and no blob.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api import openwa_webhook
from baton.channels import openwa


class TestMediaExtraction(FrappeTestCase):
    def test_media_marker_is_detected(self):
        data = {
            "id": "abc", "chatId": "123@lid", "body": "", "fromMe": False,
            "type": "image",
            "media": {"mimetype": "image/jpeg", "omitted": True, "sizeBytes": 195683},
        }
        m = openwa_webhook._extract(data)
        self.assertEqual(m["type"], "image")
        self.assertEqual(m["media"]["mimetype"], "image/jpeg")
        self.assertTrue(m["media"]["omitted"])

    def test_text_message_has_no_media(self):
        m = openwa_webhook._extract({"id": "x", "chatId": "1@c.us",
                                     "body": "hello", "type": "text"})
        self.assertIsNone(m["media"])
        self.assertEqual(m["text"], "hello")

    def test_push_name_read_from_contact_object(self):
        """OpenWA nests the sender name under `contact` on media messages."""
        m = openwa_webhook._extract({
            "id": "x", "chatId": "1@c.us", "type": "image",
            "contact": {"pushName": "Rachan"},
        })
        self.assertEqual(m["push_name"], "Rachan")

    def test_content_type_mapping(self):
        self.assertEqual(openwa.MEDIA_CONTENT_TYPES["image"], "image")
        self.assertEqual(openwa.MEDIA_CONTENT_TYPES["ptt"], "audio")
        self.assertEqual(openwa.MEDIA_CONTENT_TYPES["sticker"], "image")


class TestFetchMediaFailure(FrappeTestCase):
    """A picture that will not download is recoverable. A dropped customer
    message is not. Every failure path must return None, never raise."""

    def setUp(self):
        # fetch_media reads the connector config before it reaches requests, so
        # patching requests alone is not enough. Supplied here rather than
        # inherited from the site: these passed only while the dev site happened
        # to have OpenWA configured, and went red the moment it was switched off.
        self._saved = {
            f: frappe.db.get_single_value("Baton Settings", f)
            for f in ("openwa_enabled", "openwa_base_url", "openwa_session_id")
        }
        frappe.db.set_single_value("Baton Settings", "openwa_enabled", 1)
        frappe.db.set_single_value("Baton Settings", "openwa_base_url",
                                   "http://openwa.test:2785")
        frappe.db.set_single_value("Baton Settings", "openwa_session_id", "test-session")
        frappe.db.commit()
        # The doc cache, not the meta cache: every reader goes through
        # get_cached_doc.
        frappe.clear_document_cache("Baton Settings", "Baton Settings")
        settings = frappe.get_doc("Baton Settings")
        settings.openwa_api_key = "test-key"
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")

    def tearDown(self):
        for field, value in self._saved.items():
            frappe.db.set_single_value("Baton Settings", field, value)
        frappe.db.commit()
        frappe.clear_document_cache("Baton Settings", "Baton Settings")

    def _resp(self, status, content=b"", ctype="application/octet-stream"):
        class R:
            status_code = status
            headers = {"Content-Type": ctype}
        R.content = content
        return R()

    def test_404_returns_none(self):
        with patch.object(openwa.requests, "get", return_value=self._resp(404)):
            self.assertIsNone(openwa.fetch_media("1@lid", "m1"))

    def test_json_error_body_is_not_treated_as_media(self):
        """A 200 carrying JSON is an error envelope, not image bytes."""
        with patch.object(openwa.requests, "get",
                          return_value=self._resp(200, b'{"error":"nope"}',
                                                  "application/json; charset=utf-8")):
            self.assertIsNone(openwa.fetch_media("1@lid", "m1"))

    def test_success_returns_bytes_and_mimetype(self):
        with patch.object(openwa.requests, "get",
                          return_value=self._resp(200, b"\xff\xd8\xff", "image/jpeg")):
            blob = openwa.fetch_media("1@lid", "m1")
        self.assertEqual(blob["content"], b"\xff\xd8\xff")
        self.assertEqual(blob["mimetype"], "image/jpeg")

    def test_ids_are_url_encoded(self):
        """Chat and message ids contain @ and / and would break the path."""
        captured = {}

        def fake_get(url, **kw):
            captured["url"] = url
            return self._resp(404)

        with patch.object(openwa.requests, "get", side_effect=fake_get):
            openwa.fetch_media("213941112291503@lid", "true_x@lid_3A/33")
        self.assertNotIn("@", captured["url"].split("/messages/")[1])
        self.assertIn("%40", captured["url"])


class TestCaptionHandling(FrappeTestCase):
    """An uncaptioned media message stores its own file path in `message`.

    That is frappe_whatsapp's convention and it carries real weight: CRM's reply
    composer renders on `v-if="reply?.message"`, so blanking it makes Reply
    silently do nothing on every uncaptioned image. Suppressing the path is the
    UI's job, not the data's.
    """

    def test_uncaptioned_media_stores_its_path_not_an_empty_string(self):
        for attached, text, expected in (
            ("/private/files/x.jpg", "", "/private/files/x.jpg"),
            (None, "", "[image]"),                     # nothing arrived -> say so
            ("/private/files/x.jpg", "look", "look"),  # a real caption wins
        ):
            got = text or (attached or "[image]")
            self.assertEqual(got, expected)

    def test_private_paths_are_not_matched_by_crms_own_check(self):
        """Why the frontend needed teaching: frappe_whatsapp only suppresses
        "/files/", and Baton stores media privately."""
        self.assertFalse("/private/files/x.jpg".startswith("/files/"))

    def test_both_path_forms_match_the_shared_pattern(self):
        """The regex the frontend now uses for caption and quote suppression."""
        import re
        pattern = re.compile(r"^/(private/)?files/")
        self.assertTrue(pattern.match("/files/x.jpg"))
        self.assertTrue(pattern.match("/private/files/x.jpg"))
        self.assertFalse(pattern.match("look at this"))
        self.assertFalse(pattern.match(""))
