# -*- coding: utf-8 -*-
from odoo import fields, models

from ..services.ai_service import (
    CONFIG_API_KEY_KEY,
    CONFIG_AZURE_DEPLOYMENT_KEY,
    CONFIG_AZURE_ENDPOINT_KEY,
    CONFIG_MODEL_KEY,
    CONFIG_PROVIDER_KEY,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_business_assistant_provider = fields.Selection(
        selection=[
            ("demo", "Demo (Offline, no API key needed)"),
            ("anthropic", "Anthropic Claude"),
            ("openai", "OpenAI"),
           
        ],
        string="AI Providers",
        config_parameter=CONFIG_PROVIDER_KEY,
        default="demo",
    )
    ai_business_assistant_api_key = fields.Char(
        string="AI API Key",
        config_parameter=CONFIG_API_KEY_KEY,
    )
    ai_business_assistant_model = fields.Char(
        string="Model",
        config_parameter=CONFIG_MODEL_KEY,
        help="e.g. claude-sonnet-4-6, gpt-4o-mini. Leave empty to use "
             "the provider's default.",
    )
    ai_business_assistant_azure_endpoint = fields.Char(
        string="Azure OpenAI Endpoint",
        config_parameter=CONFIG_AZURE_ENDPOINT_KEY,
    )
    ai_business_assistant_azure_deployment = fields.Char(
        string="Azure OpenAI Deployment",
        config_parameter=CONFIG_AZURE_DEPLOYMENT_KEY,
    )
