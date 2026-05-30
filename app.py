"""
RBC — Risk Bridge Capital | Flask API
"""

import io
import json
import os

import anthropic
import pdfplumber
from flask import Flask, jsonify, render_template, request

_anthropic = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

_PDF_PROMPT = """You are an institutional options/gamma trading assistant for a SPY 0DTE scanner.

Below is raw text extracted from a daily SpotGamma PDF report.
Each PDF can be different. Some days have strong macro alerts, some days are quiet, some days mention risk-on/risk-off, OPEX, VIX, oil, rates, geopolitics, earnings, vol selling, call buying, dealer gamma, or specific levels.

Your job is NOT only to extract numbers.
Your job is to:
1. Extract objective SPY and SPX gamma levels.
2. Read the Founder’s Note / SG Summary / macro comments.
3. Understand TODAY's market regime.
4. Interpret how today's alerts change the meaning of the gamma levels.
5. Return a practical SPY 0DTE operating map.

Return ONLY valid JSON. No markdown. No explanation.

Use this exact structure:

{{
  "report_info": {{
    "date": "<report date if found>",
    "time": "<report time if found>",
    "source_type": "SpotGamma PDF"
  }},

  "daily_context": {{
    "market_regime": "<positive_gamma | negative_gamma | mixed_gamma | neutral | unknown>",
    "expected_session": "<sideways | trending_up | trending_down | volatile | compressed | unknown>",
    "risk_tone": "<risk_on | risk_off | neutral | mixed>",
    "macro_alerts": ["<oil/rates/Fed/geopolitical/earnings/OPEX/VIX alerts found>"],
    "founders_note_summary": "<2-4 sentence summary of the day in practical trading language>"
  }},

  "spx_levels": {{
    "reference_price": <number or null>,
    "resistance": [<number>, <number>],
    "pivot": <number or null>,
    "support": [<number>, <number>, <number>],
    "call_wall": <number or null>,
    "put_wall": <number or null>,
    "zero_gamma": <number or null>,
    "vol_trigger": <number or null>,
    "absolute_gamma": <number or null>,
    "implied_1d_move": <decimal or null>,
    "implied_5d_move": <decimal or null>
  }},

  "spy_levels": {{
    "reference_price": <number or null>,
    "call_wall": <number or null>,
    "put_wall": <number or null>,
    "zero_gamma": <number or null>,
    "vol_trigger": <number or null>,
    "absolute_gamma": <number or null>,
    "implied_1d_move": <decimal or null>,
    "implied_5d_move": <decimal or null>,
    "key_levels": [<number>, <number>, <number>, <number>],
    "combos": [<number>, <number>, <number>, <number>]
  }},

  "gamma_interpretation": {{
    "call_wall_meaning": "<how to interpret call wall today>",
    "put_wall_meaning": "<how to interpret put wall today>",
    "zero_gamma_meaning": "<how to interpret zero gamma today>",
    "vol_trigger_meaning": "<how to interpret volatility trigger today>",
    "absolute_gamma_meaning": "<how to interpret absolute gamma today>",
    "most_important_level_today": <number or null>,
    "why_this_level_matters": "<short explanation>"
  }},

  "spy_0dte_plan": {{
    "bias": "<bullish | bearish | neutral | neutral_to_bullish | neutral_to_bearish | mixed>",
    "preferred_trade_type": "<calls_only_above_level | puts_only_below_level | scalp_range | wait | avoid>",
    "no_trade_zone": {{
      "low": <number or null>,
      "high": <number or null>,
      "reason": "<why this area is bad/choppy>"
    }},
    "call_trigger": {{
      "level": <number or null>,
      "condition": "<confirmation needed before considering calls>"
    }},
    "put_trigger": {{
      "level": <number or null>,
      "condition": "<confirmation needed before considering puts>"
    }},
    "support_zones": [<number>, <number>, <number>],
    "resistance_zones": [<number>, <number>, <number>],
    "avoid": ["<what not to do today>"],
    "best_setup": "<best practical setup for the morning>",
    "warning": "<main risk for the trader today>"
  }},

  "sg_string": "$SPY, SPY, <call_wall>, <put_wall>, <vol_trigger>, <absolute_gamma>, <support1>, <support2>, <support3>, <combo1>, <combo2>, <combo3>, <combo4>, <implied_1d_move>, <implied_5d_move>, <zero_gamma>",

  "confidence": {{
    "level": "<high | medium | low>",
    "missing_data": ["<fields not found or uncertain>"]
  }}
}}

Rules:
- Do not invent numbers.
- If a number is not found, use null.
- implied_1d_move and implied_5d_move must be decimals. Example: 0.65% = 0.0065.
- For SPY 0DTE, interpret levels using BOTH the table and the Founder’s Note.
- Same gamma level can mean different things depending on the day:
  - Positive gamma + sideways = call wall often acts as resistance/pin zone.
  - Negative gamma + risk-off = levels can break faster and moves can expand.
  - VIX rising / macro risk = vol trigger becomes more important.
  - Risk-on + call buying = call wall can become magnet or breakout target.
- If the report says quiet/sideways/compressed, warn against chasing in the middle of the range.
- If the report says risk-on above a pivot, include that pivot as a key decision level.
- Keep all explanations short and operational.
- Return raw JSON only.

PDF TEXT:
{text}
"""