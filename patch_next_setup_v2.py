"""
RBC EUA — patch next_setup v2
Backend: next_setup calculado deterministicamente
Frontend: âncora específica dentro de showModo2Result
Uso: python3 patch_next_setup_v2.py ~/RBC/app.py ~/RBC/templates/index.html
"""
import sys, shutil, ast
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
# PATCH 1 — app.py
# ══════════════════════════════════════════════════════════════════════

OLD_APP = '''    # Resumo em uma frase
    one_sentence = (f"{gamma_regime.replace('_', ' ')}, SPY {spot_now}"
                    f" vs VT {vol_trig} — {decision}. {entry}")'''

NEW_APP = '''    # Resumo em uma frase
    one_sentence = (f"{gamma_regime.replace('_', ' ')}, SPY {spot_now}"
                    f" vs VT {vol_trig} — {decision}. {entry}")

    # ── Próximo setup a monitorar (cockpit de espera) ─────────────────
    _vt  = vol_trig
    _zg  = spy.get("zero_gamma") or vol_trig
    _cw  = call_wall
    _pw  = put_wall
    _ref = spy.get("reference_price") or spot_now

    if _vt and _zg and str(_vt) != str(_zg):
        _key_level = f"{_vt}/{_zg}"
    else:
        _key_level = str(_vt or _zg or "—")

    if gamma_regime == "NEGATIVE_GAMMA":
        next_setup = {
            "call_setup":   f"SPY recuperar {_key_level} com aceitação (fechar acima por 2+ velas).",
            "put_setup":    f"SPY retestar {_key_level} e rejeitar — confirmação de continuação baixista.",
            "no_trade":     f"SPY entre {_ref}–{_vt} sem direção clara — aguardar.",
            "key_level":    _key_level,
            "invalidation": f"Viés PUT perde força se SPY recuperar {_key_level}.",
            "context":      "NEGATIVE GAMMA — mercado frágil. Dealers amplificam moves.",
        }
    elif gamma_regime == "POSITIVE_GAMMA":
        next_setup = {
            "call_setup":   f"SPY retestar {_key_level} e segurar — entrada CALL REVERSAL perto do piso.",
            "put_setup":    f"SPY se aproximar de {_cw} e rejeitar — entrada PUT REVERSAL perto do teto.",
            "no_trade":     f"SPY no meio da faixa {_vt}–{_cw} — sem edge estrutural.",
            "key_level":    _key_level,
            "invalidation": f"Viés CALL perde força se SPY perder {_key_level}. Viés PUT perde força se SPY superar {_cw}.",
            "context":      "POSITIVE GAMMA — dealers sustentam range. Reversões nos extremos.",
        }
    else:
        next_setup = {
            "call_setup":   None,
            "put_setup":    None,
            "no_trade":     "Dados insuficientes — preencher manualmente.",
            "key_level":    None,
            "invalidation": None,
            "context":      None,
        }'''

OLD_APP_OUT = '''        "one_sentence":     one_sentence,'''
NEW_APP_OUT = '''        "one_sentence":     one_sentence,
        "next_setup":       next_setup,'''

# ══════════════════════════════════════════════════════════════════════
# PATCH 2 — index.html: âncora específica do showModo2Result
# ══════════════════════════════════════════════════════════════════════

OLD_HTML = '''</div>`;

    const box = document.getElementById('modo2-result');
    const el  = document.getElementById('modo2-result-content');
    el.style.padding = '8px';
    el.innerHTML = html;
    box.classList.add('visible');
  }

  async function runModo2() {'''

NEW_HTML = '''${(() => {
    const ns = d.next_setup;
    if (!ns) return '';
    const rowNs = (color, label, text) => !text ? '' :
      `<div style="display:flex;align-items:baseline;border-left:3px solid ${color};margin-bottom:2px;">
        <span style="min-width:90px;padding:3px 8px;font-size:10px;font-weight:700;color:${color};text-transform:uppercase;flex-shrink:0;">${label}</span>
        <span style="padding:3px 8px;font-size:11px;color:#1e293b;line-height:1.5;flex:1;">${text}</span>
      </div>`;
    return `
  <div style="background:#fff;border:0.5px solid #e2e8f0;border-left:4px solid #6366f1;border-radius:12px;overflow:hidden;">
    <div style="padding:6px 12px;font-size:10px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:.06em;border-bottom:0.5px solid #f1f5f9;background:#fafaff;">
      Próximo Setup a Monitorar
    </div>
    <div style="padding:6px 0 4px;">
      ${ns.context ? `<div style="padding:2px 12px 6px;font-size:11px;color:#64748b;font-style:italic;">${ns.context}</div>` : ''}
      ${rowNs('#16a34a', 'CALL',       ns.call_setup)}
      ${rowNs('#dc2626', 'PUT',        ns.put_setup)}
      ${rowNs('#64748b', 'NO TRADE',   ns.no_trade)}
      ${ns.key_level    ? rowNs('#6366f1', 'NÍVEL-CHAVE', ns.key_level)    : ''}
      ${ns.invalidation ? rowNs('#f97316', 'INVALIDAÇÃO', ns.invalidation) : ''}
    </div>
  </div>`;
  })()}

</div>`;

    const box = document.getElementById('modo2-result');
    const el  = document.getElementById('modo2-result-content');
    el.style.padding = '8px';
    el.innerHTML = html;
    box.classList.add('visible');
  }

  async function runModo2() {'''

# ══════════════════════════════════════════════════════════════════════
# Aplicar
# ══════════════════════════════════════════════════════════════════════

if len(sys.argv) < 3:
    print("Uso: python3 patch_next_setup_v2.py ~/RBC/app.py ~/RBC/templates/index.html")
    sys.exit(1)

app_path  = sys.argv[1]
html_path = sys.argv[2]
ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# app.py
acontent = open(app_path).read()
for old, label in [(OLD_APP, "one_sentence"), (OLD_APP_OUT, "output next_setup")]:
    if old not in acontent:
        print(f"ERRO — '{label}' não encontrado em app.py")
        sys.exit(1)
shutil.copy2(app_path, app_path.replace(".py", f"_backup_{ts}.py"))
acontent = acontent.replace(OLD_APP, NEW_APP, 1)
acontent = acontent.replace(OLD_APP_OUT, NEW_APP_OUT, 1)
ast.parse(acontent)
open(app_path, 'w').write(acontent)
print("✅ app.py — next_setup calculado e adicionado ao output")

# index.html
hcontent = open(html_path).read()
if OLD_HTML not in hcontent:
    print("ERRO — âncora showModo2Result não encontrada em index.html")
    sys.exit(1)
count = hcontent.count(OLD_HTML)
if count > 1:
    print(f"ERRO — âncora encontrada {count} vezes. Não é única.")
    sys.exit(1)
shutil.copy2(html_path, html_path.replace(".html", f"_backup_{ts}.html"))
hcontent = hcontent.replace(OLD_HTML, NEW_HTML, 1)
open(html_path, 'w').write(hcontent)
print("✅ index.html — bloco 'Próximo Setup a Monitorar' inserido no showModo2Result")
print()
print("Próximo passo:")
print("  git add app.py templates/index.html")
print('  git commit -m "APROVADO: Modo 2 cockpit — próximo setup a monitorar"')
print("  git push")
