# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..services.ai_service import get_ai_provider

_logger = logging.getLogger(__name__)

# Odoo's standard CRM activity type used for the AI-recommended activity.
# Falls back gracefully if the xmlid is missing on a given install.
AI_ACTIVITY_TYPE_XMLID = "mail.mail_activity_data_meeting"


class CrmLead(models.Model):
    _inherit = "crm.lead"

    ai_priority = fields.Selection(
        selection=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
        string="AI Priority",
        readonly=True,
        copy=False,
        help="Priority estimated by the AI Assistant on the last analysis.",
    )
    ai_intent = fields.Char(
        string="AI: Buying Intent", readonly=True, copy=False,
    )
    ai_summary = fields.Text(
        string="AI Summary", readonly=True, copy=False,
    )
    ai_next_step = fields.Char(
        string="AI: Suggested Next Step", readonly=True, copy=False,
    )
    ai_suggested_followup_date = fields.Date(
        string="AI: Suggested Follow-up Date", readonly=True, copy=False,
    )
    ai_risks = fields.Text(
        string="AI: Risks / Missing Info", readonly=True, copy=False,
    )
    ai_suggested_email = fields.Text(
        string="AI: Suggested Follow-up Email", readonly=True, copy=False,
    )
    ai_last_analyzed = fields.Datetime(
        string="AI Last Analyzed", readonly=True, copy=False,
    )
    ai_activity_created = fields.Boolean(
        string="AI Activity Created", readonly=True, copy=False, default=False,
    )

    def _build_ai_payload(self):
        """Collect the lead fields the AI provider needs, as a plain dict.

        Kept on the model (not in the service layer) since it is the
        one part that legitimately depends on Odoo's ORM/ir.model.
        """
        self.ensure_one()
        recent_messages = ""
        messages = self.message_ids.filtered(lambda m: m.message_type in ("comment", "email")).sorted(
            key=lambda m: m.date, reverse=True
        )[:3]
        if messages:
            recent_messages = " | ".join(
                (m.body or "").replace("\n", " ")[:200] for m in messages
            )
        return {
            "name": self.name,
            "partner_name": self.partner_name,
            "contact_name": self.contact_name,
            "email_from": self.email_from,
            "phone": self.phone,
            "source": self.source_id.name if self.source_id else "",
            "expected_revenue": self.expected_revenue,
            "probability": self.probability,
            "stage": self.stage_id.name if self.stage_id else "",
            "description": self.description,
            "recent_messages": recent_messages,
        }

    def action_ai_analyze(self):
        """"Analyze with AI" button handler.

        Calls the configured AI provider, stores the structured
        result on the lead, and posts a short note in the chatter for
        traceability.
        """
        self.ensure_one()
        provider = get_ai_provider(self.env)
        payload = self._build_ai_payload()
        try:
            result = provider.analyze_lead(payload)
        except UserError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any provider failure cleanly
            _logger.exception("AI Business Assistant: analysis failed for lead %s", self.id)
            raise UserError(_(
                "The AI analysis could not be completed: %s"
            ) % str(exc)) from exc

        followup_date = fields.Date.context_today(self) + timedelta(
            days=result["suggested_followup_days"]
        )

        self.write({
            "ai_priority": result["priority"],
            "ai_intent": result["intent"],
            "ai_summary": result["summary"],
            "ai_next_step": result["next_step"],
            "ai_suggested_followup_date": followup_date,
            "ai_risks": result["risks"],
            "ai_suggested_email": result["suggested_email"],
            "ai_last_analyzed": fields.Datetime.now(),
            "ai_activity_created": False,
        })

        self.message_post(
            body=_(
                "AI Assistant analysis completed — priority: %(priority)s, "
                "suggested next step: %(next_step)s."
            ) % {"priority": result["priority"].capitalize(), "next_step": result["next_step"]},
        )
        return True

    def action_ai_create_activity(self):
        """"Create Next Activity" button handler.

        Creates an Odoo mail.activity on this lead from the AI's
        recommended next step, assigned to the current salesperson
        (or the current user as a fallback).
        """
        self.ensure_one()
        if not self.ai_next_step:
            raise UserError(_(
                "Run \"Analyze with AI\" first — there is no AI "
                "recommendation to turn into an activity yet."
            ))

        activity_type = self.env.ref(AI_ACTIVITY_TYPE_XMLID, raise_if_not_found=False)
        due_date = self.ai_suggested_followup_date or fields.Date.context_today(self)
        summary = _("%s – AI recommended") % (self.ai_next_step[:110])

        self.activity_schedule(
            act_type_xmlid=AI_ACTIVITY_TYPE_XMLID if activity_type else False,
            date_deadline=due_date,
            summary=summary,
            note=self.ai_summary or "",
            user_id=self.user_id.id or self.env.user.id,
        )
        self.ai_activity_created = True
        self.message_post(
            body=_("Activity created from AI recommendation: %s") % summary,
        )
        return True
