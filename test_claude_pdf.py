import anthropic
import pdfplumber
import json

PDF_PATH = "/Users/rosi/Downloads/May22.pdf"

PROMPT = """You are a quantitative trading assistant analyzing a SpotGamma daily report for SPY 0DTE options trading.

Extract and analyze the report and return ONLY a valid JSON object with this structure:

{{
  "spy": {{
    "reference_price": null,
    "call_wall": null,
    "put_wall": null,
    "zero_gamma": null,
    "vol_trigger": null,
    "abs_gamma": null,
    "move_1d": null,
    "move_5d": null,
    "combos": [],
    "key_levels": []
  }},
  "spx": {{
    "reference_price": null,
    "pivot": null,
    "resistance": [],
    "support": [],
    "call_wall": null,
    "put_wall": null,
    "zero_gamma": null,
    "vol_trigger": null
  }},
  "regime": {{
    "gamma": null,
    "bias": null,
    "vix_posture": null,
    "summary": null
  }},
  "founder_alerts": [],
  "gamma_interpretation": null,
  "plan": {{
    "no_trade_zone": null,
    "call_trigger": null,
    "put_trigger": null,
    "avoid": null,
    "best_setup": null
  }}
}}

Rules:
- move_1d and move_5d as decimals (0.65% = 0.0065)
- If field not found use null
- Return raw JSON only, no markdown

PDF TEXT:
{text}
"""

with pdfplumber.open(PDF_PATH) as pdf:
    pages = [page.extract_text() or "" for page in pdf.pages]
text = "\n".join(pages).strip()
print(f"PDF extracted: {len(text)} chars")

client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=2048,
    messages=[{"role": "user", "content": PROMPT.format(text=text[:12000])}]
)

raw = msg.content[0].text.strip()
if raw.startswith("```"):
    raw = raw.split("\n", 1)[-1]
if raw.endswith("```"):
    raw = raw.rsplit("```", 1)[0]
raw = raw.strip()

try:
    parsed = json.loads(raw)
    print("JSON VALID")
    print(json.dumps(parsed, indent=2))
except json.JSONDecodeError as e:
    print(f"JSON ERROR: {e}")
    print(raw)
