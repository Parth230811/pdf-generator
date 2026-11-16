#!/usr/bin/env python3
"""
PDF Generator Service for the WhatsApp-to-Formal-Report pipeline.

This is the "Generate PDF" node's target in the n8n workflow
(whatsapp-report-generator.json). It receives the structured JSON that the
LLM extraction step produced, fills report_template.html with it, renders
to PDF, and returns the PDF bytes.

Run it as a small standalone web service so n8n (or Make/Pabbly) can call it
over HTTP with a simple POST — no-code tools are good at JSON branching but
none of the mainstream ones render decent PDFs from HTML for free, so this
fills that one gap with ~80 lines of code you deploy once and never touch.

-------------------------------------------------------------------------
SETUP (one time)
-------------------------------------------------------------------------
    pip install flask weasyprint

    # weasyprint needs a few system libs for font/CSS rendering:
    #   Ubuntu/Debian: sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0
    #   macOS:         brew install pango
    # See https://doc.courtbouillon.org/weasyprint/stable/first_steps.html

Run:
    python pdf_generator_service.py
    # listens on http://0.0.0.0:5000/generate-report

Deploy (so n8n can reach it from the cloud, not just localhost):
    - Easiest: Render.com / Railway.app free tier (push this file + a
      requirements.txt, it auto-detects Flask)
    - Or run on the same VM as self-hosted n8n and call it via
      http://localhost:5000/generate-report from the n8n HTTP Request node

-------------------------------------------------------------------------
REQUEST FORMAT
-------------------------------------------------------------------------
POST /generate-report
Content-Type: application/json

{
  "report_id": "RPT-1700000000000",
  "generated_at": "2026-11-16T05:30:00.000Z",
  "date": "2026-11-16",
  "location": "Shirur farm",
  "worker_name": "Ramesh Patil",
  "category": "irrigation",
  "issue_observed": "Drip irrigation pump stopped; motor likely burnt out",
  "action_taken": "Temporarily fixed using spare part",
  "quantity_or_metric": "3 acres, 4 hours without water",
  "status": "pending",
  "urgency": "medium",
  "follow_up_needed": "Replace burnt motor with new unit",
  "confidence": 0.82,
  "needs_human_review": false
}

Response: raw PDF bytes, Content-Type: application/pdf
"""

import os
import re
import html
from datetime import datetime, timezone

from flask import Flask, request, send_file, jsonify
from weasyprint import HTML
import io

app = Flask(__name__)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "report_template.html")

DEFAULTS = {
    "report_id": "N/A",
    "generated_at": "",
    "date": "Not specified",
    "location": "Not specified",
    "worker_name": "Not specified",
    "category": "other",
    "issue_observed": "Not specified",
    "action_taken": "Not specified",
    "quantity_or_metric": "Not specified",
    "status": "pending",
    "urgency": "low",
    "follow_up_needed": "None noted",
    "confidence": "",
    "needs_human_review": False,
}

SECTION_RE = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)
VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_template(template: str, data: dict) -> str:
    """Tiny mustache-style renderer: {{var}} substitution plus
    {{#section}}...{{/section}} conditional blocks. Deliberately dependency-free
    (no Jinja2) so the only pip installs you need are flask + weasyprint."""

    merged = {**DEFAULTS, **{k: v for k, v in data.items() if v not in (None, "")}}

    def section_sub(match):
        key, inner = match.group(1), match.group(2)
        return inner if merged.get(key) else ""

    out = SECTION_RE.sub(section_sub, template)

    def var_sub(match):
        key = match.group(1)
        val = merged.get(key, "")
        return html.escape(str(val))

    out = VAR_RE.sub(var_sub, out)
    return out


@app.route("/generate-report", methods=["POST"])
def generate_report():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Expected JSON body"}), 400

    if not data.get("generated_at"):
        data["generated_at"] = datetime.now(timezone.utc).isoformat()
    if not data.get("report_id"):
        data["report_id"] = f"RPT-{int(datetime.now().timestamp() * 1000)}"

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    filled_html = render_template(template, data)

    pdf_bytes = HTML(string=filled_html).write_pdf()

    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    filename = f"{data['report_id']}.pdf"

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
