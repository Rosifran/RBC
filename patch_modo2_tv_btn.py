"""
RBC EUA — patch botão TradingView no Modo 2
Adiciona botão "🔄 Usar último TradingView" que chama GET /api/tv/quote
e preenche VIX agora + SPY agora automaticamente.
Mantém campos manuais como fallback.
Não toca em app.py, motor, Modo 1 ou Modo 3.
Uso: python3 patch_modo2_tv_btn.py ~/RBC/templates/index.html
"""
import sys, shutil
from datetime import datetime

OLD = '''      <div class="form-group">
        <label class="form-label">VIX — agora <span style="color:#e53e3e">*</span></label>
        <input class="form-input" id="vix_now" type="number" step="0.01" placeholder="ex: 18.50" oninput="updateModo2Preview()">
        <span class="form-hint">VIX atual (obrigatório)</span>
      </div>
      <div class="form-group">
        <label class="form-label">SPY — agora <span style="color:#e53e3e">*</span></label>
        <input class="form-input" id="spot_now" type="number" step="0.01" placeholder="ex: 756.00" oninput="updateModo2Preview()">
        <span class="form-hint">SPY atual (obrigatório)</span>
      </div>'''

NEW = '''      <div class="form-group full" style="margin-bottom:4px;">
        <button type="button" onclick="fillFromTradingView()" style="background:#0f172a;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:12px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px;">
          🔄 Usar último TradingView
        </button>
        <span id="tv-quote-status" style="font-size:11px;color:#94a3b8;margin-top:4px;display:block;"></span>
      </div>
      <div class="form-group">
        <label class="form-label">VIX — agora <span style="color:#e53e3e">*</span></label>
        <input class="form-input" id="vix_now" type="number" step="0.01" placeholder="ex: 18.50" oninput="updateModo2Preview()">
        <span class="form-hint">VIX atual (obrigatório)</span>
      </div>
      <div class="form-group">
        <label class="form-label">SPY — agora <span style="color:#e53e3e">*</span></label>
        <input class="form-input" id="spot_now" type="number" step="0.01" placeholder="ex: 756.00" oninput="updateModo2Preview()">
        <span class="form-hint">SPY atual (obrigatório)</span>
      </div>'''

# Adiciona função fillFromTradingView antes do fechamento do script
OLD_SCRIPT_END = '  // ── Modo 2: VIX + SPY ──'

NEW_SCRIPT_END = '''  // ── TradingView auto-fill ──
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

if len(sys.argv) < 2:
    print("Uso: python3 patch_modo2_tv_btn.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

for old, label in [(OLD, "bloco VIX/SPY"), (OLD_SCRIPT_END, "âncora JS")]:
    if old not in content:
        print(f"ERRO — '{label}' não encontrado.")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".html", f"_backup_{ts}.html")
shutil.copy2(path, backup)
print(f"Backup criado: {backup}")

content = content.replace(OLD, NEW, 1)
content = content.replace(OLD_SCRIPT_END, NEW_SCRIPT_END, 1)
open(path, 'w').write(content)
print("✅ Botão TradingView adicionado no Modo 2")
print("   🔄 Usar último TradingView → preenche VIX + SPY automaticamente")
print("   Campos manuais mantidos como fallback")
