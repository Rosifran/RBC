"""
RBC — remove duplicata do botão TradingView e corrige timestamp.
Uso: python3 patch_tv_dedup.py ~/RBC/templates/index.html
"""
import sys, shutil
from datetime import datetime

# ── 1. Remove o segundo bloco do botão no HTML ────────────────────────
OLD_BTN_DUP = '''      <div class="form-group full" style="margin-bottom:4px;">
        <button type="button" onclick="fillFromTradingView()" style="background:#0f172a;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:12px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px;">
          🔄 Usar último TradingView
        </button>
        <span id="tv-quote-status" style="font-size:11px;color:#94a3b8;margin-top:4px;display:block;"></span>
      </div>
      <div class="form-group">
        <label class="form-label">VIX — agora <span style="color:#e53e3e">*</span></label>'''

NEW_BTN_ONCE = '''      <div class="form-group">
        <label class="form-label">VIX — agora <span style="color:#e53e3e">*</span></label>'''

# ── 2. Remove a segunda função fillFromTradingView no JS ──────────────
OLD_JS_DUP = '''  // ── TradingView auto-fill ──
  async function fillFromTradingView() {
    const statusEl = document.getElementById('tv-quote-status');
    statusEl.textContent = 'Buscando...';
    try {
      const res  = await fetch('/api/tv/quote');
      const data = await res.json();
      if (!data.ok || !data.spy || !data.vix) {
        statusEl.textContent = 'Sem dados recentes — preencher manualmente.';
        return;
      }
      document.getElementById('vix_now').value  = data.vix;
      document.getElementById('spot_now').value = data.spy;
      updateModo2Preview();
      const ts = data.ts ? new Date(parseInt(data.ts)).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}) : '';
      const freshMsg = data.fresh ? '✅' : '⚠ dado antigo —';
      statusEl.textContent = `${freshMsg} SPY ${data.spy} | VIX ${data.vix}${ts ? ' · ' + ts : ''}`;
    } catch(e) {
      statusEl.textContent = 'Erro ao buscar — preencher manualmente.';
    }
  }

  // ── Modo 2: VIX + SPY ──'''

NEW_JS_ONCE = '''  // ── Modo 2: VIX + SPY ──'''

# ── 3. Corrige timestamp no JS que ficou (ts é string ISO ou ms) ──────
OLD_TS = "      const ts = data.ts ? new Date(parseInt(data.ts)).toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}) : '';"
NEW_TS = "      const ts = data.ts ? (() => { const d = isNaN(data.ts) ? new Date(data.ts) : new Date(parseInt(data.ts)); return isNaN(d) ? '' : d.toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}); })() : '';"

if len(sys.argv) < 2:
    print("Uso: python3 patch_tv_dedup.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

patches = [
    (OLD_BTN_DUP,  NEW_BTN_ONCE, "botão duplicado removido"),
    (OLD_JS_DUP,   NEW_JS_ONCE,  "função JS duplicada removida"),
    (OLD_TS,       NEW_TS,       "timestamp corrigido"),
]

for old, _, label in patches:
    if old not in content:
        print(f"ERRO — '{label}' não encontrado.")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".html", f"_backup_{ts}.html")
shutil.copy2(path, backup)
print(f"Backup criado: {backup}")

for old, new, label in patches:
    content = content.replace(old, new, 1)
    print(f"✅ {label}")

open(path, 'w').write(content)
print("✅ Pronto — botão único, timestamp corrigido")
