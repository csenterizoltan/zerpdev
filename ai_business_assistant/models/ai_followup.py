# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import followup as fu
from ..services.ai_service import get_ai_provider

_logger = logging.getLogger(__name__)

SIMILAR_WINDOW_DAYS = 2  # +/- days around the deadline to call it "similar"


class AiFollowup(models.Model):
    """One AI follow-up suggestion for a lead.

    The record doubles as the editable preview (form opened in a dialog):
    while ``state == 'draft'`` the user may change every suggested value.
    The untouched AI answer is kept in ``ai_payload`` for auditing.
    """
    _name = "ai.followup"
    _description = "AI Follow-up Suggestion"
    _order = "id desc"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead", required=True, ondelete="cascade", index=True,
        readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("accepted", "Accepted"), ("discarded", "Discarded")],
        default="draft", required=True, readonly=True, index=True)
    basis = fields.Selection(
        [("analysis", "Previous AI analysis"), ("crm_data", "CRM data only")],
        readonly=True, help="What the suggestion was built from.")
    provider = fields.Char(readonly=True)
    input_hash = fields.Char(readonly=True, index=True)
    ai_payload = fields.Text(string="Original AI answer", readonly=True)
    confidence = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")], readonly=True)

    # --- editable suggestion -------------------------------------------
    channel = fields.Selection(
        [("phone", "Phone call"), ("email", "Email"),
         ("meeting", "Meeting"), ("todo", "To-Do")],
        string="Channel / Activity type", required=True, default="todo")
    deadline = fields.Date(required=True)
    deadline_reason = fields.Char()
    user_id = fields.Many2one(
        "res.users", string="Assigned to", domain=[("share", "=", False)])
    summary = fields.Char(required=True)
    goal = fields.Char()
    rationale = fields.Text(string="AI rationale")
    questions = fields.Text(string="Questions to ask", help="One per line.")
    clarify = fields.Text(string="Information to clarify", help="One per line.")
    draft_message = fields.Text(string="Draft message / call script")
    refinement = fields.Char(
        string="Guidance for regeneration",
        help="Optional hint for the AI, e.g. 'prefer a phone call'.")

    activity_id = fields.Many2one("mail.activity", readonly=True, copy=False,
                                  ondelete="set null")
    similar_activity = fields.Char(compute="_compute_similar_activity")
    confirm_duplicate = fields.Boolean(
        string="Create anyway", copy=False,
        help="Tick to create the activity although a similar one is open.")

    def init(self):
        # At most one suggestion per activity. A partial unique index works on
        # every Odoo version (NULLs are distinct anyway; this is explicit).
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ai_followup_activity_uniq "
            "ON ai_followup (activity_id) WHERE activity_id IS NOT NULL")

    # ------------------------------------------------------------------
    # Similar open activity (semantic duplicate warning)
    # ------------------------------------------------------------------
    def _find_similar_activity(self):
        self.ensure_one()
        if not (self.lead_id and self.deadline):
            return self.env["mail.activity"]
        act_type = self._activity_type()
        window = timedelta(days=SIMILAR_WINDOW_DAYS)
        domain = [
            ("res_model", "=", "crm.lead"), ("res_id", "=", self.lead_id.id),
            ("date_deadline", ">=", self.deadline - window),
            ("date_deadline", "<=", self.deadline + window),
        ]
        if act_type:
            domain.append(("activity_type_id", "=", act_type.id))
        if self.activity_id:
            domain.append(("id", "!=", self.activity_id.id))
        return self.env["mail.activity"].search(domain, limit=1)

    @api.depends("lead_id", "channel", "deadline", "activity_id", "state")
    def _compute_similar_activity(self):
        for rec in self:
            similar = rec._find_similar_activity() if rec.state == "draft" else False
            rec.similar_activity = similar and _(
                "A similar open activity already exists: \"%(s)s\" (due %(d)s).",
                s=similar.summary or similar.activity_type_id.name,
                d=similar.date_deadline) or False

    def _activity_type(self):
        self.ensure_one()
        xmlid = fu.CHANNEL_XMLIDS.get(self.channel, fu.CHANNEL_XMLIDS["todo"])
        return (self.env.ref(xmlid, raise_if_not_found=False)
                or self.env.ref(fu.CHANNEL_XMLIDS["todo"], raise_if_not_found=False))

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @api.model
    def _generate_vals(self, lead, refinement=""):
        """Call the AI once and return validated field values."""
        context, basis = lead._build_followup_context()
        provider = get_ai_provider(self.env)
        try:
            raw = provider.generate_followup(context, refinement)
        except UserError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider failures cleanly
            _logger.exception("AI Follow-up generation failed for lead %s", lead.id)
            raise UserError(_("The AI follow-up could not be generated: %s") % exc) from exc
        data = fu.normalize_followup(raw, fields.Date.context_today(lead))
        assignee = lead.user_id if lead.user_id and not lead.user_id.share else self.env.user
        return {
            "basis": basis,
            "provider": type(provider).__name__.replace("AIProvider", "").lower(),
            "input_hash": fu.input_hash([context, refinement]),
            "ai_payload": json.dumps(raw, ensure_ascii=False, default=str)[:20000],
            "confidence": data["confidence"],
            "channel": data["channel"],
            "deadline": data["deadline"],
            "deadline_reason": data["deadline_reason"],
            "user_id": assignee.id,
            "summary": data["summary"],
            "goal": data["goal"],
            "rationale": data["rationale"],
            "questions": "\n".join(data["questions"]),
            "clarify": "\n".join(data["clarify"]),
            "draft_message": data["draft_message"],
        }

    def action_regenerate(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft suggestions can be regenerated."))
        vals = self._generate_vals(self.lead_id, self.refinement or "")
        vals["confirm_duplicate"] = False
        self.write(vals)
        return self._reopen_action()

    def _reopen_action(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Follow-up"),
            "res_model": "ai.followup",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref("ai_business_assistant.ai_followup_view_form").id, "form")],
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Approval -> mail.activity
    # ------------------------------------------------------------------
    def _activity_note(self):
        self.ensure_one()

        def items(text):
            lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
            if not lines:
                return Markup("")
            return Markup("<ul>%s</ul>") % Markup("").join(
                Markup("<li>%s</li>") % l for l in lines)

        parts = []
        if self.goal:
            parts.append(Markup("<p><b>%s</b> %s</p>") % (_("Goal:"), self.goal))
        if self.deadline_reason:
            parts.append(Markup("<p><b>%s</b> %s</p>") % (_("Timing:"), self.deadline_reason))
        if self.rationale:
            parts.append(Markup("<p><b>%s</b> %s</p>") % (_("Why (AI rationale):"), self.rationale))
        if self.questions:
            parts.append(Markup("<p><b>%s</b></p>") % _("Questions to ask:"))
            parts.append(items(self.questions))
        if self.clarify:
            parts.append(Markup("<p><b>%s</b></p>") % _("Clarify:"))
            parts.append(items(self.clarify))
        if self.draft_message:
            parts.append(Markup("<p><b>%s</b><br/>%s</p>") % (
                _("Draft message:"), escape(self.draft_message).replace("\n", Markup("<br/>"))))
        parts.append(Markup("<p><i>%s</i></p>") % (
            _("Generated by AI Follow-up Generator, approved by %s.") % self.env.user.name))
        return Markup("").join(parts)

    def action_create_activity(self):
        self.ensure_one()
        # Serialize concurrent / double clicks on the same suggestion.
        self.flush_recordset()
        self.env.cr.execute("SELECT id FROM ai_followup WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset()

        if self.state == "accepted" and self.activity_id:
            return self._close_notification(
                _("This suggestion was already turned into an activity."), "warning")
        if self.state != "draft":
            raise UserError(_("This suggestion was discarded. Generate a new one."))

        today = fields.Date.context_today(self)
        if self.deadline < today or self.deadline > today + timedelta(days=fu.MAX_DEADLINE_DAYS):
            raise UserError(_("The deadline must be between today and %d days from now.")
                            % fu.MAX_DEADLINE_DAYS)
        if not self.user_id or self.user_id.share:
            raise UserError(_("Please assign the activity to an internal user."))
        if self.similar_activity and not self.confirm_duplicate:
            raise UserError(_(
                "%s\nTick \"Create anyway\" if you really want another one.")
                % self.similar_activity)

        act_type = self._activity_type()
        activity = self.lead_id.activity_schedule(
            act_type_xmlid=fu.CHANNEL_XMLIDS.get(self.channel) if act_type else False,
            date_deadline=self.deadline,
            summary=self.summary,
            note=self._activity_note(),
            user_id=self.user_id.id,
            ai_followup_id=self.id,
        )[:1]
        self.write({"state": "accepted", "activity_id": activity.id})
        self.lead_id.message_post(body=_(
            "Activity created from AI follow-up suggestion: %s") % self.summary)
        return {"type": "ir.actions.act_window_close"}

    def action_discard(self):
        self.filtered(lambda r: r.state == "draft").write({"state": "discarded"})
        return {"type": "ir.actions.act_window_close"}

    def _close_notification(self, message, kind="info"):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind, "next": {"type": "ir.actions.act_window_close"}},
        }
