# AI Business Assistant — Odoo CRM module

A small, self-contained Odoo 18 module that adds an **AI Assistant** panel
to CRM Leads/Opportunities: one click analyzes the lead with an AI model
and produces a structured recommendation (priority, intent, next step,
follow-up date, risks, draft email) — and a second click turns that
recommendation into a real Odoo Activity.

Built as a portfolio proof-of-concept: it's small enough to read end to
end in a few minutes, but structured the way a production feature would
be — provider abstraction, no hardcoded secrets, tests, demo data.

## 1. Installation

```bash
# from your Odoo addons directory
git clone <this-repo> ai_business_assistant
# or simply copy the ai_business_assistant/ folder into your addons-path

# then, with Odoo running:
# Apps > Update Apps List > search "AI Business Assistant" > Install
```

Requirements: Odoo 18.0, the standard `crm` and `mail` apps (already
part of any Odoo install), and the `requests` Python package (bundled
with Odoo's own dependencies).

## 2. Configuration

Go to **Settings > Sales > CRM > AI Assistant** (a new section added by
this module). There you can pick the AI provider and, if needed, enter
an API key.

| Setting | Notes |
|---|---|
| AI Provider | `Demo`, `Anthropic Claude`, `OpenAI`, or `Azure OpenAI` |
| API Key | Not needed for Demo. Stored as a system parameter, never in code. |
| Model | Optional override, e.g. `claude-sonnet-4-6`, `gpt-4o-mini` |
| Azure Endpoint / Deployment | Only needed for Azure OpenAI |

Nothing is hardcoded: the key and provider choice live in
`ir.config_parameter`, so they can also be set from
**Settings > Technical > Parameters > System Parameters** or via
`odoo-bin` on deploy, without touching code.

## 3. Setting up a real AI provider

- **Anthropic**: create a key in the Anthropic Console, select
  "Anthropic Claude" as provider, paste the key. Default model:
  `claude-sonnet-4-6`.
- **OpenAI**: create a key at platform.openai.com, select "OpenAI".
  Default model: `gpt-4o-mini`.
- **Azure OpenAI**: select "Azure OpenAI", fill in the API key, the
  resource endpoint (`https://<resource>.openai.azure.com`) and the
  deployment name.

## 4. Using the demo

No API key needed. The **Demo** provider is selected by default after
install, so the feature works immediately:

1. Open **CRM > any Lead/Opportunity** (two demo leads are included).
2. Click **Analyze with AI** in the header.
3. Open the new **AI Assistant** tab — priority, intent, next step,
   suggested follow-up date, risks and a draft email all appear.
4. Click **Create Next Activity** — an Odoo Activity is created from
   the recommendation, assigned to the lead's salesperson.

The demo provider is fully deterministic (rule-based on probability,
revenue and phone presence) so results are stable and repeatable for
screenshots or a recorded walkthrough.

## 4b. AI Follow-up Generator

Button **AI Follow-up** (lead form header, next to *Analyze with AI*):

1. Uses the last AI analysis if it is fresh (<= 7 days and no newer
   message); otherwise builds the suggestion directly from CRM data
   (`basis` is shown in the preview).
2. Sends one AI request with minimized context (no phone/email values,
   open activities, last 6 messages, days since last contact, language).
3. Shows an **editable preview**: channel (activity type), deadline,
   assignee, summary, goal, questions, items to clarify, rationale, draft
   message. *Regenerate* accepts an optional hint; *Cancel* discards.
4. **Create Activity** creates the `mail.activity` (rationale, questions
   and clarifications go into its note, HTML-escaped) and links it via
   `mail.activity.ai_followup_id`.

AI output is never trusted: channel is whitelisted (phone/email/meeting/
todo), deadline is clamped to 0-60 days and moved off weekends, texts
are length-limited, the assignee must be an internal user.

Duplicate protection: row lock + state check (a second click returns
"already created"), partial unique index on `ai_followup.activity_id`,
warning plus explicit *Create anyway* when a similar open activity
(same type, deadline +/- 2 days) exists, and reuse of an unchanged draft
instead of a new AI call. The Demo provider also supports the feature
(rule-based plan, no API key). History: lead > AI Assistant tab.

The old header button *Create Next Activity* was removed from the form
view (the method `action_ai_create_activity` still exists).

## 5. Architecture

```
ai_business_assistant/
├── models/
│   ├── crm_lead.py            # AI fields + analyze / create activity / action_ai_followup
│   ├── ai_followup.py         # suggestion record + editable preview + activity creation
│   ├── mail_activity.py       # ai_followup_id link
│   └── res_config_settings.py # Settings panel (provider, key, model)
├── services/
│   ├── followup.py            # pure-Python prompt, validation, demo plan
│   └── ai_service.py          # Provider-agnostic abstraction layer
│       ├── AIProviderBase
│       ├── DemoAIProvider          (offline, no key)
│       ├── AnthropicAIProvider     (Anthropic Messages API)
│       ├── OpenAIAIProvider        (OpenAI Chat Completions)
│       ├── AzureOpenAIAIProvider   (Azure-hosted OpenAI)
│       └── get_ai_provider(env)    # factory, reads ir.config_parameter
├── views/
│   ├── crm_lead_views.xml         # header buttons + "AI Assistant" notebook page
│   └── res_config_settings_views.xml
├── data/
│   ├── ai_business_assistant_data.xml  # default provider = demo
│   └── crm_lead_demo.xml               # 2 sample leads
├── security/ir.model.access.csv
└── tests/
    ├── test_ai_service.py     # provider factory + demo provider logic
    └── test_crm_lead.py       # end-to-end action tests
```

Key design decision: **`crm.lead` never imports an AI SDK or builds an
HTTP request itself.** It builds a plain dict (`_build_ai_payload`) and
calls `get_ai_provider(env).analyze_lead(payload)`. Swapping or adding
a provider is a one-file change in `services/ai_service.py`, with zero
changes to the CRM model or views.

## 6. Possible extensions

1. **Bulk analysis**: a server action / scheduled cron that
   re-analyzes stale leads (e.g. no activity in 7 days) overnight and
   surfaces a daily "leads needing attention" digest.
2. **Email send integration**: instead of just displaying the
   suggested email as text, wire "Create Next Activity" (or a new
   button) to open Odoo's `mail.compose.message` wizard pre-filled
   with the AI draft, ready to send or edit.
3. **Multi-language output**: pass the partner's/company's language
   (`self.lang`) into the prompt so the suggested email and summary
   are generated directly in Hungarian/Romanian for local SME clients
   — a natural fit given the target market of this module.
