# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged("post_install", "-at_install")
class TestCrmLeadAIAssistant(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_business_assistant.provider", "demo"
        )
        self.lead = self.env["crm.lead"].create({
            "name": "Test AI Lead",
            "partner_name": "Test Company SRL",
            "contact_name": "John Smith",
            "probability": 70,
            "expected_revenue": 5000,
            "phone": "+40 700 111 222",
        })

    def test_action_ai_analyze_populates_fields(self):
        self.lead.action_ai_analyze()
        self.assertTrue(self.lead.ai_last_analyzed)
        self.assertEqual(self.lead.ai_priority, "high")
        self.assertTrue(self.lead.ai_next_step)
        self.assertTrue(self.lead.ai_suggested_followup_date)
        self.assertFalse(self.lead.ai_activity_created)

    def test_action_ai_create_activity_requires_prior_analysis(self):
        with self.assertRaises(UserError):
            self.lead.action_ai_create_activity()

    def test_action_ai_create_activity_creates_activity(self):
        self.lead.action_ai_analyze()
        activities_before = self.env["mail.activity"].search_count(
            [("res_model", "=", "crm.lead"), ("res_id", "=", self.lead.id)]
        )
        self.lead.action_ai_create_activity()
        activities_after = self.env["mail.activity"].search_count(
            [("res_model", "=", "crm.lead"), ("res_id", "=", self.lead.id)]
        )
        self.assertEqual(activities_after, activities_before + 1)
        self.assertTrue(self.lead.ai_activity_created)
