"""
RBC EUA — patch cirúrgico Modo 3 HTML
Simplifica o formulário: remove Spot, IV, Tipo (já vêm do Modo 2).
Mantém: Prêmio, Strike, Horário, Observações.
runModo3 herda spot/vix/tipo do _modo2Data em vez dos inputs removidos.
Não toca em app.py.
Uso: python3 patch_modo3_form.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ── 1. Formulário: remove Spot, IV, Tipo ─────────────────────────────

OLD_FORM = '''    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">Spot</label>
        <input class="form-input" id="m3-spot" type="number" step="0.01" placeholder="ex: 520.00" oninput="updateModo3Preview()">
        <span class="form-hint">Preço atual do ativo-objeto</span>
      </div>
      <div class="form-group">
        <label class="form-label">IV (%)</label>
        <input class="form-input" id="m3-iv" type="number" step="0.1" placeholder="ex: 22.5" oninput="updateModo3Preview()">
        <span class="form-hint">Volatilidade implícita anualizada</span>
      </div>
      <div class="form-group">
        <label class="form-label">Prêmio <span style="color:#94a3b8;font-weight:400;">(opcional)</span></label>
        <input class="form-input" id="m3-premio" type="number" step="0.01" placeholder="ex: 1.80 — opcional">
        <span class="form-hint">Se não informado, alvo/stop serão calculados após entrada</span>
      </div>
      <div class="form-group">
        <label class="form-label">Strike</label>
        <input class="form-input" id="m3-strike" type="number" step="0.01" placeholder="ex: 525.00">
        <span class="form-hint">Strike da opção</span>
      </div>
      <div class="form-group">
        <label class="form-label">Tipo</label>
        <select class="form-input" id="m3-tipo">
          <option value="">Selecionar...</option>
          <option value="CALL">CALL</option>
          <option value="PUT">PUT</option>
        </select>
        <span class="form-hint">Direção da opção</span>
      </div>
      <div class="form-group">
        <label class="form-label">Horário (ET)</label>
        <input class="form-input" id="m3-dte" type="text" placeholder="ex: 10:15">
        <span class="form-hint">Hora da entrada (0DTE = vence hoje)</span>
      </div>
      <div class="form-group full">
        <label class="form-label">Observações operacionais</label>
        <input class="form-input" id="m3-obs" type="text" placeholder="ex: entrada no ZG, recuo do Vol Trigger...">
      </div>
    </div>'''

NEW_FORM = '''    <!-- Spot, IV e Tipo herdados do Modo 2 automaticamente -->
    <!-- inputs ocultos mantidos para compatibilidade com runModo3 -->
    <input type="hidden" id="m3-spot">
    <input type="hidden" id="m3-iv">
    <input type="hidden" id="m3-tipo">
    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">Prêmio <span style="color:#94a3b8;font-weight:400;">(opcional)</span></label>
        <input class="form-input" id="m3-premio" type="number" step="0.01" placeholder="ex: 1.80 — opcional">
        <span class="form-hint">Preencha após o fill na IBKR para calcular alvo/stop</span>
      </div>
      <div class="form-group">
        <label class="form-label">Strike escolhido</label>
        <input class="form-input" id="m3-strike" type="number" step="0.01" placeholder="ex: 525.00">
        <span class="form-hint">Strike confirmado no broker</span>
      </div>
      <div class="form-group">
        <label class="form-label">Horário de entrada (ET)</label>
        <input class="form-input" id="m3-dte" type="text" placeholder="ex: 10:15">
        <span class="form-hint">Hora da entrada (0DTE = vence hoje)</span>
      </div>
      <div class="form-group full">
        <label class="form-label">Observações operacionais</label>
        <input class="form-input" id="m3-obs" type="text" placeholder="ex: entrada no reclaim do VT, rejeição em 746...">
      </div>
    </div>'''

# ── 2. Subtítulo ──────────────────────────────────────────────────────

OLD_SUB = '  <p class="section-sub">Análise operacional 0DTE — insira spot, IV e prêmio da opção.</p>'
NEW_SUB = '  <p class="section-sub">Checklist de execução 0DTE — herda decisão do Modo 2. Informe prêmio e strike após o fill.</p>'

# ── 3. Botão "Usar dados do PDF" → "Usar decisão do Modo 2" ──────────

OLD_BTN = '      <button type="button" onclick="fillFromPDF3()" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:600;color:#334155;cursor:pointer;">📄 Usar dados do PDF</button>'
NEW_BTN = '      <button type="button" onclick="fillFromModo2()" style="background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:600;color:#334155;cursor:pointer;">⚡ Usar decisão do Modo 2</button>'

# ── 4. runModo3: herda spot/vix do _modo2Data ─────────────────────────

OLD_RUN = '''  async function runModo3() {
    const btn = document.getElementById('btn-modo3');
    btn.disabled = true;
    setLoading('modo3', true);
    showError('modo3', '');

    try {
      const spotVal = document.getElementById('m3-spot').value;
      const ivVal = document.getElementById('m3-iv').value;

      if (!_pdfData || !_pdfData.sg_string) {
        showModo3Result({});
        return;
      }

      const body = {
        // campos exigidos pelo backend atual
        sg_raw: _pdfData.sg_string,
        spot_spy: spotVal,
        vix: ivVal,

        // campos adicionais para o painel operacional
        spot: spotVal,
        iv: ivVal,
        premio: document.getElementById('m3-premio').value,
        strike: document.getElementById('m3-strike').value,
        tipo: document.getElementById('m3-tipo').value,
        dte: document.getElementById('m3-dte').value,
        observacoes: document.getElementById('m3-obs').value,
      };
      const res = await fetch('/api/modo3', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Erro no Modo 3');
      showModo3Result(data);
    } catch (e) {
      showError('modo3', e.message);
    } finally {
      setLoading('modo3', false);
      btn.disabled = false;
    }
  }'''

NEW_RUN = '''  // Preenche campos ocultos do Modo 3 a partir do Modo 2
  function fillFromModo2() {
    const spot = window._modo2Spot;
    const tipo = window._modo2Tipo;
    const vix  = window._modo2Data && window._modo2Data.vix_now;
    if (spot) document.getElementById('m3-spot').value = spot;
    if (tipo) document.getElementById('m3-tipo').value = tipo;
    if (vix)  document.getElementById('m3-iv').value   = vix;
    if (!spot && !tipo) {
      showError('modo3', 'Execute o Modo 2 primeiro.');
    }
  }

  async function runModo3() {
    const btn = document.getElementById('btn-modo3');
    btn.disabled = true;
    setLoading('modo3', true);
    showError('modo3', '');

    try {
      if (!_pdfData || !_pdfData.sg_string) {
        showModo3Result({});
        return;
      }

      // Herda spot/vix do Modo 2; fallback para inputs ocultos
      const spotVal = window._modo2Spot || document.getElementById('m3-spot').value;
      const ivVal   = (window._modo2Data && window._modo2Data.vix_now) ||
                      document.getElementById('m3-iv').value;

      // Sincroniza inputs ocultos para compatibilidade
      document.getElementById('m3-spot').value = spotVal || '';
      document.getElementById('m3-iv').value   = ivVal   || '';
      document.getElementById('m3-tipo').value = window._modo2Tipo || '';

      const body = {
        sg_raw:       _pdfData.sg_string,
        spot_spy:     spotVal,
        vix:          ivVal,
        spot:         spotVal,
        iv:           ivVal,
        premio:       document.getElementById('m3-premio').value,
        strike:       document.getElementById('m3-strike').value,
        tipo:         window._modo2Tipo || document.getElementById('m3-tipo').value,
        dte:          document.getElementById('m3-dte').value,
        observacoes:  document.getElementById('m3-obs').value,
      };
      const res = await fetch('/api/modo3', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Erro no Modo 3');
      showModo3Result(data);
    } catch (e) {
      showError('modo3', e.message);
    } finally {
      setLoading('modo3', false);
      btn.disabled = false;
    }
  }'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_modo3_form.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

patches = [
    (OLD_FORM, NEW_FORM, "formulário simplificado"),
    (OLD_SUB,  NEW_SUB,  "subtítulo atualizado"),
    (OLD_BTN,  NEW_BTN,  "botão → Usar decisão do Modo 2"),
    (OLD_RUN,  NEW_RUN,  "runModo3 herda Modo 2"),
]

for old, new, label in patches:
    if old not in content:
        print(f"ERRO — '{label}' não encontrado. Verifique o arquivo.")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".html", f"_backup_{ts}.html")
shutil.copy2(path, backup)
print(f"Backup criado: {backup}")

for old, new, label in patches:
    content = content.replace(old, new, 1)
    print(f"✅ {label}")

open(path, 'w').write(content)
print("✅ Modo 3 simplificado — herda decisão do Modo 2")
