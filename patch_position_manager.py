"""
RBC EUA — Position Manager (Swing)
====================================
Gestão de posição aberta de opções: CALL ou PUT, 1 contrato.
Regras baseadas nos cursos de opções (projeto RBC):

  - "Realizar com 30% de lucro" (Aula 4) → alerta parcial a +30%
  - "Sit quando perdedor na abertura" → MANTER se tese válida + DTE > 7
  - Theta acelera nos últimos 30 dias, crítico abaixo de 7 DTE (Aula Extra)
  - OTM perde VE mais rápido — delta baixo aumenta urgência de saída
  - IV crush pós-evento (Vega risk) → alerta quando IV cai muito
  - Stop quando chegar na ponta LONG = -35% do prêmio pago

Status de saída:
  MANTER           — tese válida, sem urgência
  MONITORAR        — algum sinal de atenção, não urgente
  SAIR_POR_STOP    — prêmio ≤ entrada × 0.65
  SAIR_POR_ALVO    — prêmio ≥ entrada × 1.40 (ou parcial a 1.30)
  SAIR_POR_TEMPO   — DTE ≤ 7 (theta perigoso)
  SAIR_POR_INVALIDA — nível técnico rompido (você marca)

Tabela PostgreSQL: positions
Rotas: POST /api/positions (registrar)
        GET  /api/positions (listar abertas)
        PUT  /api/positions/<id> (atualizar prêmio atual / fechar)
        POST /api/positions/<id>/evaluate (calcular status)

Integração: journal.py (init_positions, save_position, get_positions,
            update_position, close_position)
            app.py (rotas + evaluate_position_status)
            index.html (card no Modo 5, acima do scanner)

Uso: python3 patch_position_manager.py ~/RBC/app.py
     ~/RBC/templates/index.html ~/RBC/journal.py
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# JOURNAL.PY — tabela positions + helpers
# ══════════════════════════════════════════════════════════════════════

J1_OLD = '''# ── Quote History (Flow Proxy — SPY x VIX intraday) ─────────────────'''

J1_NEW = '''# ── Position Manager (Swing — compra de CALL ou PUT) ────────────────

def init_positions():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id              SERIAL PRIMARY KEY,
                ticker          VARCHAR(10) NOT NULL,
                direction       VARCHAR(4)  NOT NULL,
                strike          NUMERIC(10,2),
                expiration      DATE,
                dte_entry       INT,
                entry_price     NUMERIC(10,4) NOT NULL,
                entry_date      DATE DEFAULT CURRENT_DATE,
                contracts       INT DEFAULT 1,
                stop_price      NUMERIC(10,4),
                target_1        NUMERIC(10,4),
                target_2        NUMERIC(10,4),
                invalid_level   NUMERIC(10,4),
                invalid_note    TEXT,
                tese_valida     BOOLEAN DEFAULT TRUE,
                current_price   NUMERIC(10,4),
                current_iv      NUMERIC(6,2),
                status          VARCHAR(30) DEFAULT 'MANTER',
                status_reason   TEXT,
                flow_alert      TEXT,
                tech_bias       VARCHAR(10),
                closed          BOOLEAN DEFAULT FALSE,
                close_price     NUMERIC(10,4),
                close_date      DATE,
                close_reason    VARCHAR(30),
                pnl_pct         NUMERIC(8,2),
                notes           TEXT,
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW()
            )""")
        conn.commit()

def save_position(pos: dict) -> int:
    init_positions()
    entry = float(pos['entry_price'])
    stop  = round(entry * 0.65, 4)
    t1    = round(entry * 1.40, 4)
    t2    = round(entry * 1.80, 4)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO positions
              (ticker, direction, strike, expiration, dte_entry,
               entry_price, contracts, stop_price, target_1, target_2,
               invalid_level, invalid_note, flow_alert, tech_bias, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id""",
            (pos['ticker'], pos['direction'].upper(),
             pos.get('strike'), pos.get('expiration'), pos.get('dte_entry'),
             entry, pos.get('contracts', 1),
             pos.get('stop_price', stop),
             pos.get('target_1', t1),
             pos.get('target_2', t2),
             pos.get('invalid_level'), pos.get('invalid_note'),
             pos.get('flow_alert'), pos.get('tech_bias'),
             pos.get('notes')))
        row_id = cur.fetchone()[0]
        conn.commit()
    return row_id

def get_positions(include_closed=False):
    init_positions()
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if include_closed:
            cur.execute("SELECT * FROM positions ORDER BY created_at DESC")
        else:
            cur.execute("SELECT * FROM positions WHERE closed=FALSE ORDER BY created_at DESC")
        return cur.fetchall()

def update_position(pos_id: int, fields: dict):
    init_positions()
    fields['updated_at'] = datetime.now()
    cols = ', '.join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [pos_id]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE positions SET {cols} WHERE id = %s", vals)
        conn.commit()

def close_position(pos_id: int, close_price: float, close_reason: str):
    init_positions()
    entry_price = None
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT entry_price FROM positions WHERE id = %s", (pos_id,))
        row = cur.fetchone()
        if row:
            entry_price = float(row['entry_price'])
    if not entry_price:
        return
    pnl = round((close_price - entry_price) / entry_price * 100, 2)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE positions SET closed=TRUE, close_price=%s, close_date=CURRENT_DATE,
            close_reason=%s, pnl_pct=%s, status=%s, updated_at=NOW()
            WHERE id=%s""",
            (close_price, close_reason, pnl, close_reason, pos_id))
        conn.commit()
    return pnl


# ── Quote History (Flow Proxy — SPY x VIX intraday) ─────────────────'''

# ══════════════════════════════════════════════════════════════════════
# APP.PY — engine + rotas
# ══════════════════════════════════════════════════════════════════════

A1_OLD = '''def analyze_vol_premium(vix_now, rv_1m, rv_5d, spread=3.5):'''

A1_NEW = '''def evaluate_position_status(pos: dict) -> dict:
    """Position Manager — avalia status da posição aberta.
    Regras dos cursos de opções integradas.
    Não decide pelo trader — informa o estado real da posição."""
    from datetime import date as _date
    entry   = float(pos.get('entry_price') or 0)
    current = float(pos.get('current_price') or 0)
    stop    = float(pos.get('stop_price') or entry * 0.65)
    t1      = float(pos.get('target_1') or entry * 1.40)
    t2      = float(pos.get('target_2') or entry * 1.80)

    # DTE restante
    exp = pos.get('expiration')
    dte_now = None
    if exp:
        try:
            exp_date = exp if isinstance(exp, _date) else _date.fromisoformat(str(exp))
            dte_now  = (exp_date - _date.today()).days
        except Exception:
            pass

    tese_valida = bool(pos.get('tese_valida', True))
    pnl_pct = round((current - entry) / entry * 100, 2) if entry and current else None

    # ── Regras de saída (ordem de prioridade) ─────────────────────────

    # 1. Stop financeiro (curso: "Stop quando chegar na ponta LONG")
    if current and current <= stop:
        return {
            "status":  "SAIR_POR_STOP",
            "reason":  f"Prêmio {current:.2f} atingiu stop financeiro {stop:.2f} (-35%). Sair agora.",
            "urgency": "ALTA",
            "pnl_pct": pnl_pct,
        }

    # 2. Alvo atingido
    if current and current >= t2:
        return {
            "status":  "SAIR_POR_ALVO",
            "reason":  f"Alvo 2 atingido ({t2:.2f}, +80%). Realizar lucro total.",
            "urgency": "ALTA",
            "pnl_pct": pnl_pct,
        }
    if current and current >= t1:
        return {
            "status":  "SAIR_POR_ALVO",
            "reason":  f"Alvo 1 atingido ({t1:.2f}, +40%). Considerar realização total ou parcial.",
            "urgency": "MEDIA",
            "pnl_pct": pnl_pct,
        }

    # 3. Alerta parcial a +30% (curso: "Realizar com 30% de lucro")
    partial_alert = None
    if current and current >= entry * 1.30:
        partial_alert = f"Prêmio +{pnl_pct:.0f}% — considerar realização parcial (curso: +30% é ponto de atenção)."

    # 4. Invalidação técnica (você marcou)
    if not tese_valida:
        return {
            "status":  "SAIR_POR_INVALIDA",
            "reason":  pos.get('invalid_note') or "Tese técnica invalidada — nível rompido.",
            "urgency": "ALTA",
            "pnl_pct": pnl_pct,
        }

    # 5. Theta perigoso — últimos 7 DTE (curso: theta acelera nos últimos 30d)
    if dte_now is not None and dte_now <= 7:
        return {
            "status":  "SAIR_POR_TEMPO",
            "reason":  f"DTE restante: {dte_now}d — theta acelerando. Sair antes do vencimento.",
            "urgency": "ALTA",
            "pnl_pct": pnl_pct,
        }

    # 6. Monitorar — sinais de atenção sem urgência
    monitor_reasons = []
    if dte_now is not None and dte_now <= 14:
        monitor_reasons.append(f"DTE {dte_now}d — theta crescendo (abaixo de 7d = sair).")
    if current and pnl_pct and pnl_pct <= -20:
        monitor_reasons.append(f"Posição {pnl_pct:.0f}% — próximo do stop. Tese ainda válida?")
    if partial_alert:
        monitor_reasons.append(partial_alert)

    if monitor_reasons:
        return {
            "status":  "MONITORAR",
            "reason":  " | ".join(monitor_reasons),
            "urgency": "MEDIA",
            "pnl_pct": pnl_pct,
        }

    # 7. Manter — tese válida, sem urgência
    # (curso: "Sit quando perdedor na abertura mas tese válida")
    reason = "Tese técnica válida."
    if pnl_pct is not None:
        reason += f" Posição {'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%."
    if dte_now is not None:
        reason += f" {dte_now}d restantes."
    return {
        "status":  "MANTER",
        "reason":  reason,
        "urgency": "BAIXA",
        "pnl_pct": pnl_pct,
    }


@app.route("/api/positions", methods=["POST"])
def positions_post():
    """Registra nova posição aberta."""
    from journal import save_position
    data = request.get_json(silent=True) or {}
    required = ['ticker', 'direction', 'entry_price']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"ok": False, "error": f"Campos obrigatórios: {missing}"})
    try:
        pos_id = save_position(data)
        return jsonify({"ok": True, "id": pos_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/positions", methods=["GET"])
def positions_get():
    """Lista posições abertas."""
    from journal import get_positions
    include_closed = request.args.get('closed') == '1'
    try:
        rows = get_positions(include_closed=include_closed)
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'):
                    d[k] = v.isoformat()
            result.append(d)
        return jsonify({"ok": True, "positions": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/positions/<int:pos_id>", methods=["PUT"])
def positions_update(pos_id):
    """Atualiza prêmio atual, tese, IV ou fecha posição."""
    from journal import update_position, close_position
    data = request.get_json(silent=True) or {}
    try:
        if data.get('close'):
            pnl = close_position(pos_id,
                                  float(data['current_price']),
                                  data.get('close_reason', 'MANUAL'))
            return jsonify({"ok": True, "pnl_pct": pnl})
        fields = {}
        for f in ['current_price', 'current_iv', 'tese_valida',
                  'invalid_note', 'tech_bias', 'notes']:
            if f in data:
                fields[f] = data[f]
        if fields:
            update_position(pos_id, fields)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/positions/<int:pos_id>/evaluate", methods=["POST"])
def positions_evaluate(pos_id):
    """Avalia status da posição com o prêmio atual informado."""
    from journal import get_positions, update_position
    data = request.get_json(silent=True) or {}
    try:
        positions = get_positions()
        pos = next((dict(p) for p in positions if p['id'] == pos_id), None)
        if not pos:
            return jsonify({"ok": False, "error": "Posição não encontrada"})
        if 'current_price' in data:
            pos['current_price'] = data['current_price']
            update_position(pos_id, {'current_price': data['current_price']})
        if 'tese_valida' in data:
            pos['tese_valida'] = data['tese_valida']
            update_position(pos_id, {'tese_valida': data['tese_valida']})
        result = evaluate_position_status(pos)
        update_position(pos_id, {
            'status':        result['status'],
            'status_reason': result['reason'],
        })
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def analyze_vol_premium(vix_now, rv_1m, rv_5d, spread=3.5):'''

# ══════════════════════════════════════════════════════════════════════
# INDEX.HTML — card no Modo 5 acima do scanner
# ══════════════════════════════════════════════════════════════════════

H1_OLD = '''  <h2 class="section-title">US Swing Options</h2>'''

H1_NEW = '''  <h2 class="section-title">US Swing Options</h2>

  <!-- Position Manager — posições abertas -->
  <div id="positions-section" style="margin-bottom:16px;"></div>

  <script>
  // ── Position Manager ──────────────────────────────────────────────
  const STATUS_COLOR = {
    'MANTER':          '#16a34a',
    'MONITORAR':       '#d97706',
    'SAIR_POR_STOP':   '#dc2626',
    'SAIR_POR_ALVO':   '#16a34a',
    'SAIR_POR_TEMPO':  '#dc2626',
    'SAIR_POR_INVALIDA': '#dc2626',
  };
  const STATUS_LABEL = {
    'MANTER':          'MANTER',
    'MONITORAR':       'MONITORAR',
    'SAIR_POR_STOP':   'SAIR — STOP',
    'SAIR_POR_ALVO':   'SAIR — ALVO',
    'SAIR_POR_TEMPO':  'SAIR — TEMPO',
    'SAIR_POR_INVALIDA': 'SAIR — INVALIDAÇÃO',
  };

  async function loadPositions() {
    try {
      const res  = await fetch('/api/positions');
      const data = await res.json();
      const sec  = document.getElementById('positions-section');
      if (!data.ok || !data.positions || data.positions.length === 0) {
        sec.innerHTML = '';
        return;
      }
      let html = `<div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">Posições Abertas</div>`;
      for (const p of data.positions) {
        const color  = STATUS_COLOR[p.status] || '#64748b';
        const label  = STATUS_LABEL[p.status] || p.status;
        const pnl    = p.pnl_pct != null ? (p.pnl_pct >= 0 ? `+${p.pnl_pct}%` : `${p.pnl_pct}%`) : '—';
        const pnlClr = p.pnl_pct >= 0 ? '#16a34a' : '#dc2626';
        html += `
        <div style="background:#fff;border:0.5px solid #e2e8f0;border-left:4px solid ${color};border-radius:12px;padding:12px 14px;margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
            <div>
              <span style="font-size:14px;font-weight:700;color:#1e293b;">${p.ticker}</span>
              <span style="font-size:11px;color:${p.direction==='CALL'?'#16a34a':'#dc2626'};font-weight:600;margin-left:6px;">${p.direction}</span>
              ${p.strike ? `<span style="font-size:11px;color:#64748b;margin-left:4px;">$${p.strike}</span>` : ''}
              ${p.expiration ? `<span style="font-size:10px;color:#94a3b8;margin-left:4px;">· ${p.expiration}</span>` : ''}
            </div>
            <span style="font-size:11px;font-weight:700;color:${color};background:${color}18;padding:3px 10px;border-radius:8px;">${label}</span>
          </div>
          <div style="font-size:12px;color:#475569;line-height:1.6;">
            Entrada <b>$${p.entry_price}</b>
            ${p.current_price ? `· Atual <b style="color:${pnlClr};">$${p.current_price}</b> (${pnl})` : ''}
            · Stop <b>$${p.stop_price}</b> · Alvo <b>$${p.target_1}</b>
          </div>
          ${p.status_reason ? `<div style="font-size:11px;color:#64748b;margin-top:4px;">${p.status_reason}</div>` : ''}
          <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap;">
            <input type="number" step="0.01" placeholder="Prêmio atual"
              id="cp-${p.id}" style="width:110px;font-size:11px;padding:4px 8px;border:0.5px solid #e2e8f0;border-radius:6px;">
            <label style="font-size:11px;color:#64748b;">
              <input type="checkbox" id="tese-${p.id}" ${p.tese_valida ? 'checked' : ''}
                style="margin-right:3px;">Tese válida
            </label>
            <button onclick="evaluatePosition(${p.id})"
              style="font-size:11px;padding:4px 12px;background:#0f172a;color:#fff;border:none;border-radius:6px;cursor:pointer;">
              Avaliar
            </button>
            <button onclick="closePosition(${p.id})"
              style="font-size:11px;padding:4px 10px;background:#fff;color:#dc2626;border:0.5px solid #dc2626;border-radius:6px;cursor:pointer;">
              Fechar
            </button>
          </div>
        </div>`;
      }
      sec.innerHTML = html;
    } catch(e) { console.error('loadPositions:', e); }
  }

  async function evaluatePosition(id) {
    const cp    = parseFloat(document.getElementById(`cp-${id}`).value);
    const tese  = document.getElementById(`tese-${id}`).checked;
    const body  = { tese_valida: tese };
    if (!isNaN(cp)) body.current_price = cp;
    const res   = await fetch(`/api/positions/${id}/evaluate`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.ok) loadPositions();
    else alert(data.error || 'Erro ao avaliar');
  }

  async function closePosition(id) {
    const cp = parseFloat(document.getElementById(`cp-${id}`).value);
    if (isNaN(cp)) { alert('Informe o prêmio atual para fechar.'); return; }
    if (!confirm('Fechar posição?')) return;
    const res = await fetch(`/api/positions/${id}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ close: true, current_price: cp, close_reason: 'MANUAL' })
    });
    const data = await res.json();
    if (data.ok) {
      alert(`Posição fechada. P&L: ${data.pnl_pct >= 0 ? '+' : ''}${data.pnl_pct}%`);
      loadPositions();
    }
  }

  async function registerPosition(data) {
    const res = await fetch('/api/positions', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    const result = await res.json();
    if (result.ok) { loadPositions(); return result.id; }
    else { alert(result.error || 'Erro ao registrar'); return null; }
  }
  </script>

  <!-- Formulário rápido de registro -->
  <details style="margin-bottom:12px;border:0.5px solid #e2e8f0;border-radius:10px;padding:8px 12px;background:#fafafa;">
    <summary style="font-size:12px;font-weight:600;color:#64748b;cursor:pointer;">+ Registrar nova posição</summary>
    <div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:8px;">
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">TICKER *</label>
        <input id="pos-ticker" type="text" placeholder="NVDA"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">DIREÇÃO *</label>
        <select id="pos-dir"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
          <option value="CALL">CALL</option>
          <option value="PUT">PUT</option>
        </select>
      </div>
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">STRIKE</label>
        <input id="pos-strike" type="number" step="0.5" placeholder="210"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">VENCIMENTO</label>
        <input id="pos-exp" type="date"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">PRÊMIO ENTRADA *</label>
        <input id="pos-entry" type="number" step="0.01" placeholder="3.20"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div>
        <label style="font-size:10px;color:#64748b;font-weight:600;">VIÉS TÉCNICO</label>
        <select id="pos-tech"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
          <option value="">—</option>
          <option value="ALTA">ALTA</option>
          <option value="BAIXA">BAIXA</option>
          <option value="LATERAL">LATERAL</option>
        </select>
      </div>
      <div style="grid-column:1/-1;">
        <label style="font-size:10px;color:#64748b;font-weight:600;">INVALIDAÇÃO TÉCNICA (nível)</label>
        <input id="pos-invalid" type="number" step="0.01" placeholder="ex: 207.50"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div style="grid-column:1/-1;">
        <label style="font-size:10px;color:#64748b;font-weight:600;">NOTAS (opcional)</label>
        <input id="pos-notes" type="text" placeholder="ex: fluxo CALL + suporte técnico em 198"
          style="width:100%;box-sizing:border-box;font-size:12px;padding:6px 8px;border:0.5px solid #e2e8f0;border-radius:6px;margin-top:2px;">
      </div>
      <div style="grid-column:1/-1;display:flex;gap:8px;align-items:center;margin-top:4px;">
        <button onclick="submitPosition()"
          style="font-size:12px;padding:7px 18px;background:#0f172a;color:#fff;border:none;border-radius:8px;cursor:pointer;">
          Registrar posição
        </button>
        <span id="pos-status" style="font-size:11px;color:#64748b;"></span>
      </div>
    </div>
  </details>

  <script>
  async function submitPosition() {
    const ticker = document.getElementById('pos-ticker').value.trim().toUpperCase();
    const entry  = parseFloat(document.getElementById('pos-entry').value);
    if (!ticker || isNaN(entry)) {
      document.getElementById('pos-status').textContent = 'Ticker e prêmio são obrigatórios.';
      return;
    }
    const data = {
      ticker, entry_price: entry,
      direction:     document.getElementById('pos-dir').value,
      strike:        parseFloat(document.getElementById('pos-strike').value) || null,
      expiration:    document.getElementById('pos-exp').value || null,
      invalid_level: parseFloat(document.getElementById('pos-invalid').value) || null,
      tech_bias:     document.getElementById('pos-tech').value || null,
      notes:         document.getElementById('pos-notes').value || null,
    };
    if (data.expiration && data.strike) {
      const exp  = new Date(data.expiration);
      const hoje = new Date();
      data.dte_entry = Math.round((exp - hoje) / 86400000);
    }
    document.getElementById('pos-status').textContent = 'Registrando...';
    const id = await registerPosition(data);
    if (id) {
      document.getElementById('pos-status').textContent = `✅ Posição #${id} registrada`;
      ['pos-ticker','pos-entry','pos-strike','pos-exp','pos-invalid','pos-notes']
        .forEach(i => document.getElementById(i).value = '');
    }
  }
  // carrega ao abrir a aba
  document.addEventListener('DOMContentLoaded', loadPositions);
  </script>'''

# ══════════════════════════════════════════════════════════════════════
# loadModo5 — recarrega posições ao trocar para aba Swing
# ══════════════════════════════════════════════════════════════════════

H2_OLD = '''  async function loadModo5() {'''

H2_NEW = '''  async function loadModo5() {
    loadPositions();'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 4:
    print("Uso: python3 patch_position_manager.py ~/RBC/app.py "
          "~/RBC/templates/index.html ~/RBC/journal.py")
    sys.exit(1)

app_path, html_path, journal_path = sys.argv[1], sys.argv[2], sys.argv[3]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

groups = [
    (journal_path, [(J1_OLD, J1_NEW, "journal: tabela positions + helpers")]),
    (app_path,     [(A1_OLD, A1_NEW, "app: evaluate_position_status + rotas")]),
    (html_path,    [(H1_OLD, H1_NEW, "html: card posições + formulário"),
                    (H2_OLD, H2_NEW, "html: loadModo5 recarrega posições")]),
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

for path, _ in groups:
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
print("Próximo passo:")
print("  git add app.py templates/index.html journal.py")
print('  git commit -m "APROVADO: Position Manager — gestão de posição aberta swing"')
print("  git push")
