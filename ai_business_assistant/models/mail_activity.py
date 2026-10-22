# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    ai_followup_id = fields.Many2one(
        "ai.followup", string="AI Follow-up", readonly=True, copy=False,
        ondelete="set null", index=True)
    ai_generated = fields.Boolean(
        string="AI generated", compute="_compute_ai_generated", store=True)

    @api.depends("ai_followup_id")
    def _compute_ai_generated(self):
        for act in self:
            act.ai_generated = bool(act.ai_followup_id)
