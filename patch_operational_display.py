"""
RBC EUA — Patch exibicao Linha Operacional (Risk Pivot) no Modo 2
==================================================================
Adiciona ao bloco Regime, sempre visivel (inclusive em NO TRADE):

  LINHA OPERACIONAL
  Risk Pivot 739.00 · SPY +1.76% acima · ESTICADO — chase risk
  ⚠ [nota de divergencia RP/VT quando existir]

Frontend only — backend intacto.
Uso: python3 patch_operational_display.py ~/RBC/templates/index.html
"""
import sys, shutil
from datetime import datetime

OLD = '''      ${lv.put_wall ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Put Wall</div>
        <div style="font-size:16px;font-weight:500;color:#dc2626;">${parseFloat(lv.put_wall).toFixed(2)}</div>
      </div>` : ''}
    </div>
  </div>

  ${gapHtml}'''

NEW = '''      ${lv.put_wall ? `<div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Put Wall</div>
        <div style="font-size:16px;font-weight:500;color:#dc2626;">${parseFloat(lv.put_wall).toFixed(2)}</div>
      </div>` : ''}
    </div>
    ${d.operational_regime_line ? `
    <div style="padding:8px 10px;background:#fafaff;border:0.5px solid #e0e7ff;border-radius:8px;">
      <div style="font-size:10px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px;">Linha Operacional</div>
      <div style="font-size:12px;color:#1e293b;line-height:1.5;">${d.operational_regime_source === 'RISK_PIVOT' ? 'Risk Pivot' : 'Vol Trigger'} <b>${parseFloat(d.operational_regime_line).toFixed(2)}</b>${(d.distance_to_operational_pct || d.distance_to_operational_pct === 0) ? ` · SPY ${d.distance_to_operational_pct > 0 ? '+' : ''}${d.distance_to_operational_pct.toFixed(2)}% ${d.distance_to_operational_pct >= 0 ? 'acima' : 'abaixo'}` : ''}${d.regime_strength === 'extended' ? ` <span style="color:#dc2626;font-weight:600;">· ESTICADO — chase risk</span>` : d.regime_strength === 'transition' ? ` <span style="color:#d97706;font-weight:600;">· zona de TRANSICAO — toque nao e aceitacao</span>` : d.regime_strength === 'clear' ? ` <span style="color:#16a34a;">· regime claro</span>` : d.regime_strength === 'moderate' ? ` <span style="color:#64748b;">· regime moderado</span>` : ''}</div>
      ${d.operational_note ? `<div style="font-size:11px;color:#92400e;margin-top:4px;">⚠ ${d.operational_note}</div>` : ''}
    </div>` : ''}
  </div>

  ${gapHtml}'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_operational_display.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

n = content.count(OLD)
if n == 0:
    print("ERRO — ancora nao encontrada.")
    sys.exit(1)
if n > 1:
    print(f"ERRO — ancora encontrada {n}x.")
    sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".html", f"_backup_{ts}.html"))
print("Backup criado")

content = content.replace(OLD, NEW, 1)
open(path, 'w').write(content)
print("✅ Linha Operacional visivel no bloco Regime — inclusive em NO TRADE")
print()
print("Proximo passo:")
print("  git add templates/index.html")
print('  git commit -m "APROVADO: exibicao Linha Operacional (Risk Pivot) no Modo 2"')
print("  git push")
