# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..services import followup as fu


@tagged("post_install", "-at_install")
class TestFollowupLogic(TransactionCase):
    """Pure validation logic (no ORM needed, but runs in the suite)."""

    def test_normalize_clamps_untrusted_output(self):
        res = fu.normalize_followup({
            "channel": "WhatsApp", "days_from_today": 9999, "goal": "x" * 999,
            "questions_to_ask": ["a"] * 20, "confidence": "??",
        }, date(2026, 10, 22))
        self.assertEqual(res["channel"], "todo")
        self.assertLessEqual((res["deadline"] - date(2026, 10, 22)).days, 62)
        self.assertLess(res["deadline"].weekday(), 5)
        self.assertEqual(len(res["goal"]), 200)
        self.assertEqual(len(res["questions"]), fu.MAX_LIST_ITEMS)
        self.assertEqual(res["confidence"], "medium")

    def test_weekend_moves_to_monday(self):
        res = fu.normalize_followup({"days_from_today": 2}, date(2026, 10, 23))  # Fri+2=Sun
        self.assertEqual(res["deadline"], date(2026, 10, 26))


@tagged("post_install", "-at_install")
class TestAiFollowup(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_business_assistant.provider", "demo")
        self.lead = self.env["crm.lead"].create({
            "name": "FU Lead", "partner_name": "Acme SRL", "contact_name": "Jane",
            "probability": 70, "expected_revenue": 5000, "phone": "+40 700 111 222",
            "user_id": self.env.user.id,
        })

    def _activities(self):
        return self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"), ("res_id", "=", self.lead.id)])

    def test_no_analysis_uses_crm_data(self):
        self.lead.action_ai_followup()
        fup = self.lead.ai_followup_ids
        self.assertEqual(fup.basis, "crm_data")
        self.assertEqual(fup.state, "draft")
        self.assertFalse(self._activities())  # nothing created before approval

    def test_fresh_analysis_is_used(self):
        self.lead.action_ai_analyze()
        self.lead.action_ai_followup()
        self.assertEqual(self.lead.ai_followup_ids.basis, "analysis")

    def test_repeated_click_reuses_draft(self):
        self.lead.action_ai_followup()
        self.lead.action_ai_followup()
        self.assertEqual(len(self.lead.ai_followup_ids), 1)

    def test_create_activity_and_double_click(self):
        self.lead.action_ai_followup()
        fup = self.lead.ai_followup_ids
        fup.goal = "<script>alert(1)</script>"
        fup.action_create_activity()
        fup.action_create_activity()  # second click: no error, no duplicate
        acts = self._activities()
        self.assertEqual(len(acts), 1)
        self.assertEqual(fup.state, "accepted")
        self.assertEqual(acts.ai_followup_id, fup)
        self.assertTrue(acts.ai_generated)
        self.assertNotIn("<script>", acts.note)
        self.assertIn("&lt;script&gt;", acts.note)

    def test_similar_activity_requires_confirmation(self):
        self.lead.action_ai_followup()
        fup = self.lead.ai_followup_ids
        fup.action_create_activity()
        self.lead.action_ai_followup()  # new draft: unchanged hash? open act changed it
        new = self.lead.ai_followup_ids.filtered(lambda f: f.state == "draft")
        new.deadline = fup.deadline
        new.channel = fup.channel
        self.assertTrue(new.similar_activity)
        with self.assertRaises(UserError):
            new.action_create_activity()
        new.confirm_duplicate = True
        new.action_create_activity()
        self.assertEqual(len(self._activities()), 2)

    def test_past_deadline_rejected(self):
        self.lead.action_ai_followup()
        fup = self.lead.ai_followup_ids
        fup.deadline = date(2020, 1, 1)
        with self.assertRaises(UserError):
            fup.action_create_activity()

    def test_discard_and_regenerate(self):
        self.lead.action_ai_followup()
        fup = self.lead.ai_followup_ids
        fup.refinement = "prefer a phone call"
        fup.action_regenerate()
        self.assertEqual(fup.state, "draft")
        fup.action_discard()
        self.assertEqual(fup.state, "discarded")
        with self.assertRaises(UserError):
            fup.action_create_activity()
