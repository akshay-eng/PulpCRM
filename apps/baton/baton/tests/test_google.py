"""Google sign-in and per-user Gmail sending.

One pair of Google Cloud credentials has to drive two different OAuth flows.
These pin the wiring, because the failure mode when it is half-done is a
`redirect_uri_mismatch` from Google that says nothing about which half.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.api import google


def _cleanup():
    for name in frappe.get_all("Connected App",
                               filters={"provider_name": google.CONNECTED_APP},
                               pluck="name"):
        frappe.delete_doc("Connected App", name, force=True, ignore_permissions=True)
    name = frappe.db.get_value("Social Login Key",
                               {"social_login_provider": "Google"}, "name")
    if name:
        frappe.delete_doc("Social Login Key", name, force=True, ignore_permissions=True)
    frappe.db.set_single_value("Google Settings", "enable", 0)
    frappe.db.set_single_value("Google Settings", "client_id", "")
    frappe.db.commit()


class TestGoogleSetup(FrappeTestCase):
    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_saving_once_wires_up_both_flows(self):
        """Sign-in and mail are separate OAuth flows sharing one client. Asking
        for the credentials twice is how people end up with two half-configured
        apps."""
        out = google.save_google(client_id="abc.apps.googleusercontent.com",
                                 client_secret="s3cret", enable_login=1)
        self.assertTrue(out["has_client_secret"])
        self.assertTrue(out["login_enabled"])

        key = frappe.db.get_value("Social Login Key",
                                  {"social_login_provider": "Google"},
                                  ["client_id", "enable_social_login", "sign_ups"],
                                  as_dict=True)
        self.assertEqual(key.client_id, "abc.apps.googleusercontent.com")
        self.assertTrue(key.enable_social_login)
        # A Google login that silently creates accounts turns any Google address
        # into a CRM user.
        self.assertEqual(key.sign_ups, "Deny")

        app = google._mail_app()
        self.assertIsNotNone(app, "the mail OAuth client must exist")
        self.assertEqual(app.client_id, "abc.apps.googleusercontent.com")
        self.assertIn(google.GMAIL_SCOPE, [s.scope for s in app.scopes])

    def test_the_mail_client_asks_for_a_refresh_token(self):
        """Google only returns one when asked, and only once unless consent is
        forced -- without both, sending works for an hour and then stops."""
        google.save_google(client_id="abc", client_secret="s3cret")
        app = google._mail_app()
        params = {q.key: q.value for q in app.query_parameters}
        self.assertEqual(params.get("access_type"), "offline")
        self.assertEqual(params.get("prompt"), "consent")

    def test_the_secret_is_never_returned(self):
        google.save_google(client_id="abc", client_secret="s3cret")
        blob = frappe.as_json(google.get_google_status())
        self.assertNotIn("s3cret", blob)

    def test_saving_again_without_a_secret_keeps_the_stored_one(self):
        google.save_google(client_id="abc", client_secret="s3cret")
        google.save_google(client_id="def", client_secret=None)
        self.assertTrue(google.get_google_status()["has_client_secret"])
        self.assertEqual(google.get_google_status()["client_id"], "def")

    def test_both_redirect_uris_are_offered_once_set_up(self):
        google.save_google(client_id="abc", client_secret="s3cret")
        uris = google.redirect_uris()
        self.assertIn("login_via_google", uris["login"])
        # Frappe composes this one and appends the app's document name, so a
        # guessed URI would fail only at consent time.
        self.assertIn("connected_app.callback", uris["mail"])
        self.assertIn(google._mail_app().name.replace(" ", "%20"),
                      uris["mail"].replace(" ", "%20"))

    def test_connecting_a_mailbox_before_setup_says_so(self):
        with self.assertRaises(frappe.ValidationError) as e:
            google.connect_my_gmail("me@example.com")
        self.assertIn("not set up", str(e.exception))

    def test_connecting_creates_the_account_before_the_consent_trip(self):
        """A successful consent that lands with nowhere to store the token is a
        connection that silently did nothing."""
        from unittest.mock import patch

        google.save_google(client_id="abc", client_secret="s3cret")
        with patch("frappe.integrations.doctype.connected_app.connected_app"
                   ".ConnectedApp.initiate_web_application_flow",
                   return_value="https://accounts.google.com/o/oauth2/v2/auth?x=1"):
            out = google.connect_my_gmail("probe-gmail@example.com", make_default=0)

        self.assertIn("accounts.google.com", out["url"])
        account = frappe.get_doc("Email Account", out["account"])
        self.assertEqual(account.auth_method, "OAuth")
        self.assertEqual(account.service, "GMail")
        self.assertEqual(account.connected_user, frappe.session.user)
        self.assertTrue(account.enable_outgoing)
        frappe.delete_doc("Email Account", out["account"], force=True,
                          ignore_permissions=True)
        frappe.db.commit()
