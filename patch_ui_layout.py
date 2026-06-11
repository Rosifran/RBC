#!/usr/bin/env python3
"""
patch_ui_layout.py — Layout global: aproveitar a largura do desktop.
Rodar de dentro de ~/RBC:  python3 patch_ui_layout.py

Diagnóstico (2026-06-11):
- A única classe limitando a largura é .tab-panel (linha ~103):
      max-width: 860px  ->  todos os 5 Modos presos a 860px.
- Não existe .container/.main separado; o painel da aba É o container.
- Todos os grids internos usam frações (1fr/minmax) -> expandem sozinhos.
- box-sizing: border-box global (linha 26) -> width calc é seguro.

Mudança (APENAS CSS):
  .tab-panel: width calc(100% - 48px), max-width 1280px, margin 0 auto
  + @media 768px: largura total e padding reduzido no celular
Nada de backend, rotas, JSON, decisões, cálculos ou comportamento de botões.
Idempotente, com backup.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = ROOT / 'templates' / 'index.html'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')

OLD = """  .tab-panel { display: none; padding: 40px; max-width: 860px; }
  .tab-panel.active { display: block; }"""

NEW = """  .tab-panel {
    display: none;
    padding: 40px;
    width: calc(100% - 48px);
    max-width: 1280px;
    margin: 0 auto;
  }
  .tab-panel.active { display: block; }

  @media (max-width: 768px) {
    .tab-panel { width: 100%; padding: 24px 16px; }
  }"""


def main():
    print("patch_ui_layout.py — largura global 860px -> 1280px\n")
    if not INDEX.exists():
        print("ERRO: templates/index.html nao encontrado. Rode de dentro de ~/RBC.")
        sys.exit(1)
    text = INDEX.read_text(encoding='utf-8')
    if "max-width: 1280px" in text:
        print("  ja aplicado — nada a fazer.")
        return
    if text.count(OLD) != 1:
        print(f"  anchor encontrado {text.count(OLD)}x (esperado 1) — abortado. Nada alterado.")
        sys.exit(1)

    dst = INDEX.with_name(f"index_backup_{TS}.html")
    shutil.copy2(INDEX, dst)
    print(f"  backup: templates/{dst.name}")

    INDEX.write_text(text.replace(OLD, NEW), encoding='utf-8')
    print("  CSS .tab-panel: OK (1280px desktop, centralizado, mobile ajustado)")
    print("""
Proximos passos:
  git add templates/index.html patch_ui_layout.py
  git commit -m "UI: layout global usa largura do desktop (tab-panel 860->1280px + media query mobile)"
  git push
Apos o deploy: Cmd+Shift+R em qualquer Modo.
""")


if __name__ == '__main__':
    main()
