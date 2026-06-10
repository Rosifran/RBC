#!/usr/bin/env python3
"""
patch_modo5_dedup.py (v4) — Corrige duplicação de linhas no Modo 5.
Rodar de dentro de ~/RBC:  python3 patch_modo5_dedup.py

Bug: get_swing_latest_scan() (journal.py) filtra por scan_date (o DIA).
Com 2+ scans no mesmo dia, todos voltam misturados -> linhas duplicadas
por ticker/direcao no dashboard (scan 10:34 sem capital_fit + scan 12:56
com capital_fit, lado a lado).

Fix: DISTINCT ON (ticker, direction) mantendo o registro mais recente
(created_at DESC) dentro do dia mais recente. 1 linha por par, sempre
a mais nova. Nao mexe em salvamento, schema, scanner ou frontend.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
JOURNAL = ROOT / 'journal.py'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')

OLD = '''            # Busca todos os registros desse scan
            cur.execute("""
                SELECT * FROM swing_scans
                WHERE scan_date = (SELECT scan_date FROM swing_scans ORDER BY created_at DESC LIMIT 1)
                ORDER BY ticker, direction
            """)'''

NEW = '''            # Busca os registros do dia mais recente — 1 linha por ticker+direcao
            # (DISTINCT ON mantem o registro mais novo quando ha varios scans no dia)
            cur.execute("""
                SELECT DISTINCT ON (ticker, direction) * FROM swing_scans
                WHERE scan_date = (SELECT scan_date FROM swing_scans ORDER BY created_at DESC LIMIT 1)
                ORDER BY ticker, direction, created_at DESC
            """)'''


def main():
    print("patch_modo5_dedup.py (v4) — 1 linha por ticker+direcao\n")
    if not JOURNAL.exists():
        print("ERRO: journal.py nao encontrado. Rode de dentro de ~/RBC.")
        sys.exit(1)
    text = JOURNAL.read_text(encoding='utf-8')
    if "DISTINCT ON (ticker, direction)" in text:
        print("  ja aplicado — nada a fazer.")
        return
    if text.count(OLD) != 1:
        print(f"  anchor encontrado {text.count(OLD)}x (esperado 1) — abortado.")
        sys.exit(1)

    dst = JOURNAL.with_name(f"journal_backup_{TS}.py")
    shutil.copy2(JOURNAL, dst)
    print(f"  backup: {dst.name}")

    JOURNAL.write_text(text.replace(OLD, NEW), encoding='utf-8')
    import py_compile
    py_compile.compile(str(JOURNAL), doraise=True)
    print("  journal.py: patch OK, sintaxe OK")
    print("""
Proximos passos:
  git add journal.py patch_modo5_dedup.py
  git commit -m "Modo 5: dedup get_swing_latest_scan (DISTINCT ON ticker+direction)"
  git push
Apos o deploy: Cmd+Shift+R no Modo 5 — deve sobrar 1 linha por ticker/direcao.
""")


if __name__ == '__main__':
    main()
