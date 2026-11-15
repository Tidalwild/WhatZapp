import unittest

from wake.scope import contact_in_scope, default_scope, normalize_scope


class ScopeTests(unittest.TestCase):
    def test_default_is_nobody_and_groups_stay_out(self):
        self.assertFalse(contact_in_scope(default_scope(), label="contact-a", kind="direct"))
        direct = {"mode": "direct", "allow": [], "deny": ["contact-c"], "groups": "exclude", "maxReplies": 2}
        self.assertTrue(contact_in_scope(direct, label="contact-a", kind="direct"))
        self.assertTrue(contact_in_scope(direct, label="contact-b", kind="direct"))
        self.assertFalse(contact_in_scope(direct, label="contact-c", kind="direct"))
        self.assertFalse(contact_in_scope(direct, label="room", kind="group"))
        self.assertFalse(contact_in_scope(direct, label="room", kind="unknown"))
        included = {**direct, "groups": "include"}
        self.assertTrue(contact_in_scope(included, label="room", kind="group"))
        named = normalize_scope({"mode": "allowlist", "allow": ["contact-a", "bad name"], "deny": [], "groups": "exclude", "maxReplies": 0})
        self.assertEqual(named["allow"], ["contact-a"])
        self.assertFalse(contact_in_scope(named, label="contact-b", kind="direct"))
        self.assertEqual(named["maxReplies"], 0)
