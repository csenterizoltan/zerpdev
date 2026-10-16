# -*- coding: utf-8 -*-
{
    "name": "AI Business Assistant",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "AI-powered lead analysis and next-step automation for CRM",
    "description": """
AI Business Assistant
======================

Adds an "AI Assistant" panel to CRM Leads/Opportunities that:

* Analyzes a lead with a single click ("Analyze with AI")
* Produces a structured summary: priority, buying intent, next step,
  suggested follow-up date, risks, and a draft follow-up email
* Lets the user create the AI-recommended next Activity with one click
  ("Create Next Activity")

The AI provider is fully abstracted behind a small service layer
(`services/ai_service.py`) so the backend (OpenAI, Azure OpenAI,
Anthropic, a local LLM, or a built-in offline demo provider) can be
swapped via configuration only — no code changes required.

Ships with a Demo AI provider so the whole feature can be shown,
screenshotted and demoed without any API key at all.
    """,
    "author": "Csenteri Zoltán",
    "website": "https://www.linkedin.com/in/csenzol",
    "license": "LGPL-3",
    "depends": ["crm", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/crm_lead_views.xml",
        "data/ai_business_assistant_data.xml",
    ],
    "demo": [
        "data/crm_lead_demo.xml",
    ],
    "installable": True,
    #"application": True,
    #"auto_install": False,
}
