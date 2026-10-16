# -*- coding: utf-8 -*-
"""
AI provider abstraction layer for the AI Business Assistant module.

The CRM model never talks to an AI vendor SDK directly. It only ever
calls ``get_ai_provider(env).analyze_lead(payload)``. This keeps the
CRM layer free of vendor-specific logic and makes it trivial to add a
new backend (or switch the default one) purely through configuration
(Settings > Technical > Parameters > System Parameters, or the
dedicated Settings panel this module adds).

Supported providers out of the box:
    - "demo"       : no API key needed, deterministic canned answers.
    - "anthropic"  : Anthropic Claude (Messages API).
    - "openai"     : OpenAI Chat Completions API.
    - "azure_openai": Azure-hosted OpenAI deployment.

To add a new provider:
    1. Subclass ``AIProviderBase``.
    2. Implement ``analyze_lead(self, payload)`` returning a dict that
       matches the ``AI_ANALYSIS_SCHEMA`` keys documented below.
    3. Register it in ``_PROVIDER_REGISTRY``.

Expected return shape from ``analyze_lead``:
    {
        "summary": str,
        "priority": "low" | "medium" | "high",
        "intent": str,
        "next_step": str,
        "suggested_followup_days": int,
        "risks": str,
        "suggested_email": str,
    }
"""

import json
import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # seconds, for outbound HTTP calls to AI providers

CONFIG_PROVIDER_KEY = "ai_business_assistant.provider"
CONFIG_API_KEY_KEY = "ai_business_assistant.api_key"
CONFIG_MODEL_KEY = "ai_business_assistant.model"
CONFIG_AZURE_ENDPOINT_KEY = "ai_business_assistant.azure_endpoint"
CONFIG_AZURE_DEPLOYMENT_KEY = "ai_business_assistant.azure_deployment"

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "azure_openai": "gpt-4o-mini",
}


def _build_prompt(payload):
    """Build a single natural-language prompt describing the lead.

    Kept provider-agnostic on purpose: every provider receives the
    same instructions and only the transport differs.
    """
    lines = [
        "You are a CRM sales assistant. Analyze the following lead and "
        "respond ONLY with a compact JSON object (no markdown, no "
        "prose outside the JSON) with exactly these keys: "
        "summary (string, 2-3 sentences), "
        "priority (one of: low, medium, high), "
        "intent (short string describing buying intent/interest level), "
        "next_step (short string, one recommended next action), "
        "suggested_followup_days (integer, days from today), "
        "risks (short string listing risks or missing information), "
        "suggested_email (a short, professional follow-up email, "
        "plain text, no subject line).",
        "",
        "Lead data:",
        f"- Name: {payload.get('name') or 'n/a'}",
        f"- Company: {payload.get('partner_name') or 'n/a'}",
        f"- Contact: {payload.get('contact_name') or 'n/a'}",
        f"- Email: {payload.get('email_from') or 'n/a'}",
        f"- Phone: {payload.get('phone') or 'n/a'}",
        f"- Source: {payload.get('source') or 'n/a'}",
        f"- Expected revenue: {payload.get('expected_revenue') or 'n/a'}",
        f"- Probability: {payload.get('probability') or 'n/a'}",
        f"- Stage: {payload.get('stage') or 'n/a'}",
        f"- Description / notes: {payload.get('description') or 'n/a'}",
        f"- Last messages / log: {payload.get('recent_messages') or 'n/a'}",
    ]
    return "\n".join(lines)


def _safe_json_loads(text):
    """Best-effort JSON extraction from a model response.

    Models occasionally wrap JSON in markdown fences despite
    instructions not to; strip those before parsing.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
    cleaned = cleaned.replace("json\n", "", 1) if cleaned.startswith("json\n") else cleaned
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except (ValueError, TypeError):
                pass
    raise UserError(_(
        "The AI provider returned a response that could not be parsed "
        "as JSON. Please try again or switch to the Demo provider."
    ))


def _normalize_result(data):
    """Fill in safe defaults so callers never have to guard for
    missing keys, and clamp priority to the allowed values."""
    priority = str(data.get("priority", "medium")).strip().lower()
    if priority not in ("low", "medium", "high"):
        priority = "medium"
    try:
        followup_days = int(data.get("suggested_followup_days", 3))
    except (TypeError, ValueError):
        followup_days = 3
    followup_days = max(0, min(followup_days, 60))
    return {
        "summary": data.get("summary") or "",
        "priority": priority,
        "intent": data.get("intent") or "",
        "next_step": data.get("next_step") or "",
        "suggested_followup_days": followup_days,
        "risks": data.get("risks") or "",
        "suggested_email": data.get("suggested_email") or "",
    }


class AIProviderBase:
    """Base interface every AI provider must implement."""

    def __init__(self, env):
        self.env = env

    def analyze_lead(self, payload):
        """Return a normalized analysis dict for the given lead payload.

        ``payload`` is a plain dict built by ``crm.lead._build_ai_payload()``.
        """
        raise NotImplementedError


class DemoAIProvider(AIProviderBase):
    """Deterministic, offline provider used for demos and screenshots.

    Requires no API key and no network access, so the full feature
    (including "Create Next Activity") can be shown end-to-end from a
    fresh Odoo install.
    """

    def analyze_lead(self, payload):
        has_revenue = bool(payload.get("expected_revenue"))
        has_phone = bool(payload.get("phone"))
        probability = payload.get("probability") or 0

        if probability and probability >= 60:
            priority = "high"
            intent = "Strong buying intent — actively engaging"
            next_step = "Schedule a 30-minute discovery call within 2 days"
            followup_days = 2
        elif probability and probability >= 30:
            priority = "medium"
            intent = "Moderate interest — evaluating options"
            next_step = "Send a tailored proposal and follow up by phone"
            followup_days = 4
        else:
            priority = "low"
            intent = "Early-stage interest — not yet qualified"
            next_step = "Send an introductory email with case studies"
            followup_days = 7

        missing = []
        if not has_revenue:
            missing.append("expected revenue")
        if not has_phone:
            missing.append("phone number")
        risks = (
            "Missing: " + ", ".join(missing) + "."
            if missing else "No major gaps detected in the lead data."
        )

        contact = payload.get("contact_name") or payload.get("partner_name") or "there"
        company = payload.get("partner_name") or "your company"
        summary = (
            f"{contact} from {company} has shown {intent.lower()}. "
            f"Recommended next step: {next_step.lower()}."
        )
        suggested_email = (
            f"Hi {contact},\n\n"
            f"Thank you for your interest — it was great learning more about "
            f"{company}'s needs. Based on our conversation so far, I'd "
            f"suggest we {next_step[0].lower() + next_step[1:]}.\n\n"
            f"Would a slot in the next few days work for you?\n\n"
            f"Best regards,"
        )

        return _normalize_result({
            "summary": summary,
            "priority": priority,
            "intent": intent,
            "next_step": next_step,
            "suggested_followup_days": followup_days,
            "risks": risks,
            "suggested_email": suggested_email,
        })


class AnthropicAIProvider(AIProviderBase):
    """Calls the Anthropic Messages API."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def analyze_lead(self, payload):
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param(CONFIG_API_KEY_KEY)
        if not api_key:
            raise UserError(_(
                "No Anthropic API key configured. Go to Settings > "
                "AI Assistant to add one, or switch to the Demo provider."
            ))
        model = icp.get_param(CONFIG_MODEL_KEY) or DEFAULT_MODELS["anthropic"]
        prompt = _build_prompt(payload)

        response = requests.post(
            self.API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code != 200:
            _logger.error("Anthropic API error: %s %s", response.status_code, response.text)
            raise UserError(_(
                "The Anthropic API returned an error (%s). Please check "
                "your API key and try again."
            ) % response.status_code)

        data = response.json()
        text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        parsed = _safe_json_loads("\n".join(text_blocks))
        return _normalize_result(parsed)


class OpenAIAIProvider(AIProviderBase):
    """Calls the OpenAI Chat Completions API."""

    API_URL = "https://api.openai.com/v1/chat/completions"

    def analyze_lead(self, payload):
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param(CONFIG_API_KEY_KEY)
        if not api_key:
            raise UserError(_(
                "No OpenAI API key configured. Go to Settings > AI "
                "Assistant to add one, or switch to the Demo provider."
            ))
        model = icp.get_param(CONFIG_MODEL_KEY) or DEFAULT_MODELS["openai"]
        prompt = _build_prompt(payload)

        response = requests.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code != 200:
            _logger.error("OpenAI API error: %s %s", response.status_code, response.text)
            raise UserError(_(
                "The OpenAI API returned an error (%s). Please check "
                "your API key and try again."
            ) % response.status_code)

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _safe_json_loads(content)
        return _normalize_result(parsed)


class AzureOpenAIAIProvider(AIProviderBase):
    """Calls an Azure OpenAI deployment (Chat Completions compatible API)."""

    def analyze_lead(self, payload):
        icp = self.env["ir.config_parameter"].sudo()
        api_key = icp.get_param(CONFIG_API_KEY_KEY)
        endpoint = icp.get_param(CONFIG_AZURE_ENDPOINT_KEY)
        deployment = icp.get_param(CONFIG_AZURE_DEPLOYMENT_KEY)
        if not (api_key and endpoint and deployment):
            raise UserError(_(
                "Azure OpenAI is not fully configured (API key, endpoint "
                "and deployment name are all required). Go to Settings > "
                "AI Assistant, or switch to the Demo provider."
            ))
        prompt = _build_prompt(payload)
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
            "/chat/completions?api-version=2024-02-15-preview"
        )

        response = requests.post(
            url,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code != 200:
            _logger.error("Azure OpenAI API error: %s %s", response.status_code, response.text)
            raise UserError(_(
                "The Azure OpenAI API returned an error (%s). Please "
                "check your configuration and try again."
            ) % response.status_code)

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _safe_json_loads(content)
        return _normalize_result(parsed)


_PROVIDER_REGISTRY = {
    "demo": DemoAIProvider,
    "anthropic": AnthropicAIProvider,
    "openai": OpenAIAIProvider,
    "azure_openai": AzureOpenAIAIProvider,
}


def get_ai_provider(env):
    """Factory: returns the configured AI provider instance.

    Defaults to the Demo provider when none is configured, so the
    module always works out of the box.
    """
    provider_key = env["ir.config_parameter"].sudo().get_param(
        CONFIG_PROVIDER_KEY, default="demo"
    )
    provider_cls = _PROVIDER_REGISTRY.get(provider_key, DemoAIProvider)
    return provider_cls(env)
