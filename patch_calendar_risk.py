"""
RBC EUA — Patch 4: Calendar Risk Engine (curso SpotGamma)
==========================================================
1. journal.py — tabela calendar_events (upsert) + helpers
2. app.py    — parser do calendario SpotGamma + /api/calendar (POST/GET)
               + analyze_calendar_risk (eventos do banco + OPEX e VIX
               expiration CALCULADOS por regra) + integracao no Modo 2
3. index.html — area colapsada no Modo 1 para colar o calendario
               + badge no card Decisao + linha no Intelligence Overlay
               (pontos 1 e 2 do mockup aprovado)

Severidade: CPI/Inflation/FOMC/Payroll = 3 (EXTREME no dia, HIGH vespera)
            PCE/PPI/GDP = 2 | Retail/Michigan/Housing etc = 1
Risco:      LOW 0 | MEDIUM -1 | HIGH -2 | EXTREME -3 (score_impact)
Regra aprovada: HIGH/EXTREME → reasons + rebaixa GOOD→CAUTION.
NAO bloqueia sozinho (bloqueio por calendario entra com o Decision Score).
Auto-monitoramento: cobertura < 7 dias → aviso "colar atualizacao".

NAO altera: motor, decision, entry/stop/targets, next_setup,
evaluate_hard_blocks (ajuste e pos-processamento externo), Modo 3, Journal.

Uso: python3 patch_calendar_risk.py ~/RBC/app.py ~/RBC/templates/index.html ~/RBC/journal.py
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# JOURNAL.PY — 1 substituição
# ══════════════════════════════════════════════════════════════════════

J1_OLD = '''from datetime import datetime as _dt_swing'''

J1_NEW = '''# ── Calendar events (Calendar Risk Engine) ──────────────────────────

def init_calendar():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                event_date DATE NOT NULL,
                event_name VARCHAR(120) NOT NULL,
                event_time VARCHAR(24),
                importance INT DEFAULT 1,
                PRIMARY KEY (event_date, event_name)
            )""")
        conn.commit()

def save_calendar_events(events):
    """Upsert de eventos: [{date, name, time, importance}]. Sem duplicar."""
    if not events:
        return 0
    init_calendar()
    n = 0
    with get_conn() as conn, conn.cursor() as cur:
        for ev in events:
            cur.execute("""
                INSERT INTO calendar_events (event_date, event_name, event_time, importance)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_date, event_name)
                DO UPDATE SET event_time = EXCLUDED.event_time,
                              importance = EXCLUDED.importance
            """, (ev["date"], ev["name"][:120], ev.get("time"), ev.get("importance", 1)))
            n += 1
        conn.commit()
    return n

def get_calendar_events(from_date=None):
    init_calendar()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if from_date:
            cur.execute("SELECT * FROM calendar_events WHERE event_date >= %s ORDER BY event_date",
                        (from_date,))
        else:
            cur.execute("SELECT * FROM calendar_events ORDER BY event_date")
        return cur.fetchall()


from datetime import datetime as _dt_swing'''

# ══════════════════════════════════════════════════════════════════════
# APP.PY — 3 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Engine + rotas após o tv_quote_get
A1_OLD = '''    return jsonify({
        "ok":     bool(spy and vix),
        "spy":    spy,
        "vix":    vix,
        "ts":     ts_str,
        "fresh":  fresh,
        "message": None if fresh else "Dado com mais de 30 min — confirmar manualmente.",
    })'''

A1_NEW = '''    return jsonify({
        "ok":     bool(spy and vix),
        "spy":    spy,
        "vix":    vix,
        "ts":     ts_str,
        "fresh":  fresh,
        "message": None if fresh else "Dado com mais de 30 min — confirmar manualmente.",
    })


# ── Calendar Risk Engine (curso SpotGamma) ──────────────────────────

_CAL_EXTREME = ("cpi", "inflation rate", "core inflation", "fomc",
                "fed interest rate", "fed press conference",
                "nonfarm", "payroll")
_CAL_HIGH    = ("pce", "ppi", "producer price", "gdp",
                "economic projections", "jackson hole")
_CAL_MEDIUM  = ("retail sales", "michigan", "consumer sentiment", "ism",
                "jolts", "unemployment", "housing starts",
                "building permits", "durable goods", "personal income",
                "confidence")

def _cal_importance(name):
    n = (name or "").lower()
    if any(k in n for k in _CAL_EXTREME):
        return 3
    if any(k in n for k in _CAL_HIGH):
        return 2
    if any(k in n for k in _CAL_MEDIUM):
        return 1
    return 0

def _parse_sg_calendar(raw):
    """Parser do calendario colado do SpotGamma.
    Formato: 'Wednesday 06-10 08:30 am EDT' / 'US' / '!!!' / 'Nome (May)'"""
    import re
    from datetime import date as _date
    events, pend_date, pend_time = [], None, None
    today = _date.today()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^[A-Za-z]+\\s+(\\d{1,2})-(\\d{1,2})\\s+(\\d{1,2}:\\d{2})\\s*(am|pm)', line, re.I)
        if m:
            mm, dd = int(m.group(1)), int(m.group(2))
            yy = today.year if mm >= today.month else today.year + 1
            try:
                pend_date = _date(yy, mm, dd).isoformat()
                pend_time = f"{m.group(3)} {m.group(4).lower()} ET"
            except ValueError:
                pend_date = None
            continue
        if line.upper() == "US" or set(line) <= set("!"):
            continue
        if pend_date:
            events.append({"date": pend_date, "name": line, "time": pend_time,
                           "importance": _cal_importance(line)})
    return events

def _third_friday(year, month):
    from datetime import date as _date, timedelta as _td
    d = _date(year, month, 1)
    fridays = 0
    while True:
        if d.weekday() == 4:
            fridays += 1
            if fridays == 3:
                return d
        d += _td(days=1)

def _today_et():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).date()

def analyze_calendar_risk(today=None):
    """Eventos do banco + OPEX e VIX expiration calculados por regra."""
    from datetime import timedelta as _td, date as _date
    from journal import get_calendar_events
    today = today or _today_et()
    tomorrow = today + _td(days=1)

    rows = get_calendar_events(from_date=today.isoformat())
    ev_today    = [r for r in rows if str(r["event_date"]) == today.isoformat()]
    ev_tomorrow = [r for r in rows if str(r["event_date"]) == tomorrow.isoformat()]
    coverage    = max([str(r["event_date"]) for r in rows], default=None)
    needs_update = (not coverage) or (_date.fromisoformat(coverage) < today + _td(days=7))

    # OPEX = 3a sexta do mes (proxima, se a deste mes ja passou)
    opex = _third_friday(today.year, today.month)
    if opex < today:
        nm = today.month % 12 + 1
        ny = today.year + (1 if nm == 1 else 0)
        opex = _third_friday(ny, nm)
    opex_week = (opex - _td(days=opex.weekday())) <= today <= opex

    # VIX expiration = 30 dias antes da 3a sexta do mes seguinte
    nm = today.month % 12 + 1
    ny = today.year + (1 if nm == 1 else 0)
    vix_exp = _third_friday(ny, nm) - _td(days=30)
    if vix_exp < today:
        nm2 = nm % 12 + 1
        ny2 = ny + (1 if nm2 == 1 else 0)
        vix_exp = _third_friday(ny2, nm2) - _td(days=30)
    _vw_start = vix_exp - _td(days=vix_exp.weekday())
    vix_exp_week = _vw_start <= today <= _vw_start + _td(days=6)

    week_end = today + _td(days=6 - today.weekday())
    fomc_week = any(
        ("fomc" in (r["event_name"] or "").lower()
         or "fed interest" in (r["event_name"] or "").lower())
        for r in rows
        if today.isoformat() <= str(r["event_date"]) <= week_end.isoformat())

    max_today    = max([r.get("importance") or 0 for r in ev_today], default=0)
    max_tomorrow = max([r.get("importance") or 0 for r in ev_tomorrow], default=0)

    if max_today >= 3:
        risk = "EXTREME"
    elif max_tomorrow >= 3 or max_today == 2 or (opex_week and fomc_week):
        risk = "HIGH"
    elif max_tomorrow == 2 or max_today == 1 or opex_week or vix_exp_week:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    def _top_name(evs):
        evs = sorted(evs, key=lambda r: -(r.get("importance") or 0))
        return evs[0]["event_name"] if evs else None

    label = None
    if ev_today and max_today >= max_tomorrow:
        label = f"{_top_name(ev_today)} hoje"
    elif ev_tomorrow and max_tomorrow > 0:
        label = f"{_top_name(ev_tomorrow)} amanha"
    elif opex_week and fomc_week:
        label = "Semana OPEX + FOMC"
    elif vix_exp_week:
        label = "Semana VIX expiration"
    elif opex_week:
        label = "Semana de OPEX"

    note = None
    if risk == "EXTREME":
        note = (f"Calendario EXTREME: {label}. Volatilidade sticky, opcoes caras. "
                f"Exigir confirmacao extra ou estrutura — tamanho reduzido.")
    elif risk == "HIGH":
        note = f"Calendario HIGH: {label}. Exigir confirmacao extra."
    elif risk == "MEDIUM" and label:
        note = f"Calendario: {label}."

    return {
        "risk_level":      risk,
        "score_impact":    {"LOW": 0, "MEDIUM": -1, "HIGH": -2, "EXTREME": -3}[risk],
        "label":           label,
        "note":            note,
        "events_today":    [{"name": r["event_name"], "time": r.get("event_time")} for r in ev_today],
        "events_tomorrow": [{"name": r["event_name"], "time": r.get("event_time")} for r in ev_tomorrow],
        "opex_week":       opex_week,
        "opex_date":       opex.isoformat(),
        "vix_exp_week":    vix_exp_week,
        "vix_exp_date":    vix_exp.isoformat(),
        "fomc_week":       fomc_week,
        "coverage_until":  coverage,
        "needs_update":    needs_update,
    }

@app.route("/api/calendar", methods=["POST"])
def calendar_post():
    """Recebe o texto colado do SpotGamma, parseia e salva (upsert)."""
    from journal import save_calendar_events
    data = request.get_json(silent=True) or {}
    events = _parse_sg_calendar(data.get("raw") or "")
    if not events:
        return jsonify({"ok": False, "error": "Nenhum evento reconhecido no texto."})
    n = save_calendar_events(events)
    coverage = max(e["date"] for e in events)
    return jsonify({"ok": True, "saved": n, "coverage_until": coverage})

@app.route("/api/calendar", methods=["GET"])
def calendar_get():
    try:
        return jsonify({"ok": True, **analyze_calendar_risk()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})'''

# 2. Integração no Modo 2 (antes/depois do evaluate_hard_blocks)
A2_OLD = '''    # ── Hard Blocks — camada de inteligencia pos-motor ────────────────
    intelligence_block = evaluate_hard_blocks(
        decision, gamma_regime, regime_strength, regime_zone,
        operational_note, location, anchors,
        at_move_high, at_move_low, next_setup)'''

A2_NEW = '''    # ── Calendar Risk Engine (curso SpotGamma) ────────────────────────
    try:
        calendar_risk = analyze_calendar_risk()
    except Exception as _cal_err:
        calendar_risk = {"risk_level": "LOW", "score_impact": 0, "label": None,
                         "note": None, "events_today": [], "events_tomorrow": [],
                         "opex_week": False, "vix_exp_week": False,
                         "fomc_week": False, "coverage_until": None,
                         "needs_update": False, "error": str(_cal_err)}

    # ── Hard Blocks — camada de inteligencia pos-motor ────────────────
    intelligence_block = evaluate_hard_blocks(
        decision, gamma_regime, regime_strength, regime_zone,
        operational_note, location, anchors,
        at_move_high, at_move_low, next_setup)

    # Calendar ajusta a qualidade (regra aprovada: sem bloquear ate o Score)
    if calendar_risk.get("risk_level") in ("HIGH", "EXTREME"):
        if calendar_risk.get("note"):
            intelligence_block["reasons"].append(calendar_risk["note"])
        if intelligence_block.get("entry_quality") == "GOOD":
            intelligence_block["entry_quality"] = "CAUTION"'''

# 3. Output
A3_OLD = '''        "intelligence_block": intelligence_block,'''

A3_NEW = '''        "intelligence_block": intelligence_block,
        "calendar_risk":    calendar_risk,'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — 4 substituições
# ══════════════════════════════════════════════════════════════════════

# 1. Badge no card Decisao (ponto 1 do mockup)
H1_OLD = '''      <div style="text-align:right;">
        <span style="font-size:11px;background:${statusBg};color:${statusColor};padding:3px 10px;border-radius:8px;font-weight:500;">${status}</span>
        <div style="font-size:10px;color:#64748b;margin-top:4px;">Score ${sc}/5 · Risco ${d.risk || '—'}</div>
      </div>'''

H1_NEW = '''      <div style="text-align:right;">
        ${(d.calendar_risk && d.calendar_risk.label && ['MEDIUM','HIGH','EXTREME'].indexOf(d.calendar_risk.risk_level) >= 0) ? `<div style="margin-bottom:4px;"><span style="font-size:11px;background:${d.calendar_risk.risk_level==='EXTREME'?'#fef2f2':d.calendar_risk.risk_level==='HIGH'?'#fff7ed':'#fffbeb'};color:${d.calendar_risk.risk_level==='EXTREME'?'#991b1b':d.calendar_risk.risk_level==='HIGH'?'#9a3412':'#92400e'};padding:3px 10px;border-radius:8px;font-weight:600;">📅 ${d.calendar_risk.label} · ${d.calendar_risk.risk_level}</span></div>` : ''}
        ${(d.calendar_risk && d.calendar_risk.needs_update) ? `<div style="margin-bottom:4px;"><span style="font-size:10px;background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:8px;">📅 Calendario ate ${d.calendar_risk.coverage_until || '—'} — colar atualizacao no Modo 1</span></div>` : ''}
        <span style="font-size:11px;background:${statusBg};color:${statusColor};padding:3px 10px;border-radius:8px;font-weight:500;">${status}</span>
        <div style="font-size:10px;color:#64748b;margin-top:4px;">Score ${sc}/5 · Risco ${d.risk || '—'}</div>
      </div>'''

# 2. Linha no Intelligence Overlay (ponto 2 do mockup)
H2_OLD = '''    ${ib.alternative ? `<div style="font-size:11px;color:#64748b;margin-top:4px;"><b>Alternativa:</b> ${ib.alternative}</div>` : ''}
  </div>`;'''

H2_NEW = '''    ${ib.alternative ? `<div style="font-size:11px;color:#64748b;margin-top:4px;"><b>Alternativa:</b> ${ib.alternative}</div>` : ''}
    ${(d.calendar_risk && d.calendar_risk.note && ['HIGH','EXTREME'].indexOf(d.calendar_risk.risk_level) >= 0) ? `<div style="font-size:11px;color:#7c2d12;margin-top:6px;padding-top:6px;border-top:0.5px solid rgba(0,0,0,0.08);">📅 ${d.calendar_risk.note}</div>` : ''}
  </div>`;'''

# 3. Área colapsada no Modo 1
H3_OLD = '''    <h3 class="section-title" style="font-size:16px;margin-bottom:20px">Executar Modo 1</h3>'''

H3_NEW = '''    <details style="margin-bottom:16px;border:0.5px solid #e2e8f0;border-radius:10px;padding:8px 12px;background:#fafafa;">
      <summary style="font-size:12px;font-weight:600;color:#64748b;cursor:pointer;">📅 Calendário econômico (colar do SpotGamma)</summary>
      <div style="margin-top:8px;">
        <textarea id="cal-paste" rows="5" placeholder="Cole aqui o calendário do SpotGamma (Important Dates)..." style="width:100%;box-sizing:border-box;font-size:11px;font-family:monospace;border:0.5px solid #e2e8f0;border-radius:8px;padding:8px;"></textarea>
        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
          <button type="button" onclick="saveCalendar()" style="font-size:12px;padding:6px 14px;border:0.5px solid #cbd5e1;border-radius:8px;background:#fff;cursor:pointer;">Salvar calendário</button>
          <span id="cal-status" style="font-size:11px;color:#64748b;"></span>
        </div>
      </div>
    </details>
    <h3 class="section-title" style="font-size:16px;margin-bottom:20px">Executar Modo 1</h3>'''

# 4. Função saveCalendar
H4_OLD = '''  async function runModo1() {'''

H4_NEW = '''  async function saveCalendar() {
    const txt = document.getElementById('cal-paste').value;
    const st  = document.getElementById('cal-status');
    if (!txt.trim()) { st.textContent = 'Cole o texto primeiro.'; return; }
    st.textContent = 'Salvando...';
    try {
      const res = await fetch('/api/calendar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw: txt })
      });
      const data = await res.json();
      st.textContent = data.ok
        ? `✅ ${data.saved} eventos salvos — cobertura até ${data.coverage_until}`
        : (data.error || 'Erro ao salvar');
    } catch (e) { st.textContent = 'Erro: ' + e.message; }
  }

  async function runModo1() {'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 4:
    print("Uso: python3 patch_calendar_risk.py ~/RBC/app.py ~/RBC/templates/index.html ~/RBC/journal.py")
    sys.exit(1)

app_path, html_path, journal_path = sys.argv[1], sys.argv[2], sys.argv[3]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

groups = [
    (journal_path, [(J1_OLD, J1_NEW, "journal: calendar_events + helpers")]),
    (app_path,     [(A1_OLD, A1_NEW, "app: engine + rotas /api/calendar"),
                    (A2_OLD, A2_NEW, "app: integracao Modo 2 (GOOD→CAUTION)"),
                    (A3_OLD, A3_NEW, "app: calendar_risk no output")]),
    (html_path,    [(H1_OLD, H1_NEW, "html: badge no card Decisao"),
                    (H2_OLD, H2_NEW, "html: linha no overlay"),
                    (H3_OLD, H3_NEW, "html: area colapsada Modo 1"),
                    (H4_OLD, H4_NEW, "html: funcao saveCalendar")]),
]

contents = {}
for path, patches in groups:
    c = open(path).read()
    for old, _, label in patches:
        n = c.count(old)
        if n != 1:
            print(f"ERRO — '{label}': ancora encontrada {n}x em {path}")
            sys.exit(1)
    contents[path] = c

for path, patches in groups:
    ext = path.rsplit(".", 1)[1]
    shutil.copy2(path, path.replace(f".{ext}", f"_backup_{ts}.{ext}"))
print(f"Backups criados ({ts})")

for path, patches in groups:
    c = contents[path]
    for old, new, label in patches:
        c = c.replace(old, new, 1)
        print(f"✅ {label}")
    if path.endswith(".py"):
        ast.parse(c)
    open(path, 'w').write(c)

print()
print("Apos o deploy:")
print("  1. Abrir o site → Modo 1 → '📅 Calendario economico' → colar o texto do SpotGamma → Salvar")
print("  2. Rodar o Modo 2 — hoje (CPI) deve mostrar badge EXTREME + linha no overlay")
print()
print("Proximo passo:")
print("  git add app.py templates/index.html journal.py")
print('  git commit -m "APROVADO: Patch 4 — Calendar Risk Engine completo"')
print("  git push")
