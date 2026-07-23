"""
RBC EUA — Fix updateModo2Preview (TypeError no console)
========================================================
A funcao referencia elementos de uma versao antiga do formulario
(m2-spy, modo2-metrics, m2-*-display) que nao existem mais.
Fix: null-safe — verifica existencia antes de ler .value.
Uso: python3 patch_fix_preview.py ~/RBC/templates/index.html
"""
import sys, shutil
from datetime import datetime

OLD = '''  // ── Modo 2: VIX + SPY ──
  function updateModo2Preview() {
    const vix = document.getElementById('m2-vix').value;
    const spy = document.getElementById('m2-spy').value;
    const show = vix || spy;
    document.getElementById('modo2-metrics').style.display = show ? 'flex' : 'none';
    if (vix) document.getElementById('m2-vix-display').textContent = parseFloat(vix).toFixed(2);
    if (spy) document.getElementById('m2-spy-display').textContent = parseFloat(spy).toFixed(2);
  }'''

NEW = '''  // ── Modo 2: VIX + SPY ── (null-safe: elementos podem nao existir)
  function updateModo2Preview() {
    const vixEl = document.getElementById('m2-vix');
    const spyEl = document.getElementById('m2-spy');
    const vix = vixEl ? vixEl.value : '';
    const spy = spyEl ? spyEl.value : '';
    const metricsEl = document.getElementById('modo2-metrics');
    if (metricsEl) metricsEl.style.display = (vix || spy) ? 'flex' : 'none';
    const vd = document.getElementById('m2-vix-display');
    const sd = document.getElementById('m2-spy-display');
    if (vix && vd) vd.textContent = parseFloat(vix).toFixed(2);
    if (spy && sd) sd.textContent = parseFloat(spy).toFixed(2);
  }'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_fix_preview.py ~/RBC/templates/index.html")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

n = content.count(OLD)
if n != 1:
    print(f"ERRO — ancora encontrada {n}x.")
    sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".html", f"_backup_{ts}.html"))
print("Backup criado")

content = content.replace(OLD, NEW, 1)
open(path, 'w').write(content)
print("✅ updateModo2Preview null-safe — TypeError eliminado")
