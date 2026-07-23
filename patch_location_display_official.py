"""
RBC EUA — Location Engine como fonte oficial de localizacao (frontend)
=======================================================================
Substitui os textos antigos de range pelo location_report:

  1. Bloco NO TRADE: reason antigo → d.location.location_report
     Cards de extremos: target_1/target_2 com labels fixos (bug 755/755)
     → nearest_resistance/nearest_support com tipos reais
  2. Acao agora: acaoDesc usa location_report quando existir

Fallback: se location nao existir, comportamento antigo preservado.
Frontend only — motor, decision, entry, stop, targets intactos.

Uso: python3 patch_location_display_official.py ~/RBC/templates/index.html
"""
import sys, shutil
from datetime import datetime

# 1. Bloco NO TRADE: report + extremos do Location Engine
H1_OLD = '''  <div style="background:#f8fafc;border-radius:12px;padding:10px 14px;">
    <div style="font-size:12px;color:#64748b;line-height:1.6;">${d.reason || 'SPY no meio da faixa, sem edge estrutural.'}</div>
    ${d.target_1 && d.target_2 ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;">
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Extremo superior</div>
        <div style="font-size:14px;font-weight:500;color:#16a34a;">${parseFloat(d.target_1) > parseFloat(d.target_2) ? d.target_1 : d.target_2}</div>
        <div style="font-size:10px;color:#94a3b8;">Call Wall / resistencia</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Extremo inferior</div>
        <div style="font-size:14px;font-weight:500;color:#dc2626;">${parseFloat(d.target_1) < parseFloat(d.target_2) ? d.target_1 : d.target_2}</div>
        <div style="font-size:10px;color:#94a3b8;">Vol Trigger / suporte</div>
      </div>
    </div>` : ''}
  </div>`}'''

H1_NEW = '''  <div style="background:#f8fafc;border-radius:12px;padding:10px 14px;">
    <div style="font-size:12px;color:#64748b;line-height:1.6;">${(d.location && d.location.location_report) ? d.location.location_report : (d.reason || 'SPY no meio da faixa, sem edge estrutural.')}</div>
    ${d.location && d.location.nearest_resistance && d.location.nearest_support ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;">
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Resistência mais próxima</div>
        <div style="font-size:14px;font-weight:500;color:#16a34a;">${d.location.nearest_resistance}</div>
        <div style="font-size:10px;color:#94a3b8;">${d.location.nearest_resistance_type || ''}</div>
      </div>
      <div style="background:#f8fafc;border-radius:8px;padding:8px 10px;">
        <div style="font-size:10px;color:#64748b;">Suporte mais próximo</div>
        <div style="font-size:14px;font-weight:500;color:#dc2626;">${d.location.nearest_support}</div>
        <div style="font-size:10px;color:#94a3b8;">${d.location.nearest_support_type || ''}</div>
      </div>
    </div>` : ''}
  </div>`}'''

# 2. Acao agora: location_report como fonte oficial
H2_OLD = '''    } else if (isNo) {
      acaoAgora = 'NAO ENTRAR';
      acaoDesc  = d.reason || 'SPY no meio da faixa, sem edge estrutural.';'''

H2_NEW = '''    } else if (isNo) {
      acaoAgora = 'NAO ENTRAR';
      acaoDesc  = (d.location && d.location.location_report) ? d.location.location_report : (d.reason || 'SPY no meio da faixa, sem edge estrutural.');'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_location_display_official.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

for old, label in [(H1_OLD, "bloco NO TRADE + extremos"), (H2_OLD, "acao agora")]:
    n = content.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".html", f"_backup_{ts}.html"))
print("Backup criado")

content = content.replace(H1_OLD, H1_NEW, 1)
content = content.replace(H2_OLD, H2_NEW, 1)
open(path, 'w').write(content)
print("✅ Location Engine = fonte oficial de localizacao na tela")
print()
print("Proximo passo:")
print("  git add templates/index.html")
print('  git commit -m "APROVADO: location_report como fonte oficial — extremos com tipos reais"')
print("  git push")
