# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

from ..services.ai_service import DemoAIProvider, get_ai_provider


@tagged("post_install", "-at_install")
class TestAIService(TransactionCase):

    def test_demo_provider_returns_normalized_result(self):
        provider = DemoAIProvider(self.env)
        result = provider.analyze_lead({
            "name": "Test Lead",
            "partner_name": "Acme SRL",
            "contact_name": "Jane Doe",
            "probability": 75,
            "expected_revenue": 1000,
            "phone": "+40 700 000 000",
        })
        self.assertIn(result["priority"], ("low", "medium", "high"))
        self.assertEqual(result["priority"], "high")
        self.assertTrue(result["summary"])
        self.assertTrue(result["suggested_email"])
        self.assertIsInstance(result["suggested_followup_days"], int)

    def test_demo_provider_flags_missing_data_as_risk(self):
        provider = DemoAIProvider(self.env)
        result = provider.analyze_lead({"name": "Bare Lead", "probability": 10})
        self.assertIn("expected revenue", result["risks"])
        self.assertIn("phone number", result["risks"])

    def test_get_ai_provider_defaults_to_demo(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_business_assistant.provider", "demo"
        )
        provider = get_ai_provider(self.env)
        self.assertIsInstance(provider, DemoAIProvider)

    def test_get_ai_provider_falls_back_on_unknown_key(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_business_assistant.provider", "not_a_real_provider"
        )
        provider = get_ai_provider(self.env)
        self.assertIsInstance(provider, DemoAIProvider)
