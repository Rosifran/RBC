#!/usr/bin/env python3
"""
patch_capital_fit_v2.py — Capital Fit no output do TERMINAL do scanner.
Rodar de dentro de ~/RBC:  python3 patch_capital_fit_v2.py
Pré-requisito: patch_capital_fit.py (v1) já aplicado.

O que muda (item 3 da validação GPT):
  E1 — move enrich_scan_results para DENTRO do loop, antes do print_result
       (cada resultado já sai enriquecido no terminal e no salvamento)
  E2 — remove o bloco de enriquecimento pós-loop (fica redundante)
  E3 — print_result ganha o bloco "Capital Fit" abaixo do "Score detalhe"

Não mexe: IBKR, tickers, score técnico, filtros, seleção de contratos,
frontend (já patcheado na v1). Idempotente, com backup.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SCANNER = ROOT / 'us_swing_ibkr.py'
TS = datetime.now().strftime('%Y%m%d_%H%M%S')


def apply(path: Path, old: str, new: str, label: str, marker: str) -> bool:
    text = path.read_text(encoding='utf-8')
    if marker in text:
        print(f"  {label}: ja aplicado — pulando.")
        return False
    if text.count(old) != 1:
        print(f"  {label}: anchor encontrado {text.count(old)}x (esperado 1) — abortado.")
        return False
    path.write_text(text.replace(old, new), encoding='utf-8')
    print(f"  {label}: OK")
    return True


# E1 — enriquecer cada resultado antes do print
E1_OLD = """            r = scan_ticker(ib, ticker, direction)
            results.append(r)
            print_result(r)"""

E1_NEW = """            r = scan_ticker(ib, ticker, direction)
            # Capital Fit — enriquece ANTES do print e do salvamento (so adiciona campos)
            try:
                from capital_fit_engine import enrich_scan_results
                enrich_scan_results([r])
            except Exception as cf_err:
                print(f"  Aviso: capital_fit indisponivel — {cf_err}")
            results.append(r)
            print_result(r)"""

# E2 — remover bloco pós-loop (redundante após E1)
E2_OLD = """    ib.disconnect()

    # Capital Fit Engine — camada de adequacao de capital (nao altera score tecnico)
    try:
        from capital_fit_engine import enrich_scan_results
        enrich_scan_results(results)
        print("  Capital Fit aplicado aos contratos.")
    except Exception as cf_err:
        print(f"  Aviso: capital_fit indisponivel — {cf_err}")

    save_results(results)"""

E2_NEW = """    ib.disconnect()
    save_results(results)"""

# E3 — bloco Capital Fit no print_result, abaixo do Score detalhe
E3_OLD = """        print(f"  Score detalhe:")
        for k, note in c['score_notes'].items():
            s  = c['score_detail'][k]
            si = "\u2705" if s == 2 else "\u26a0" if s == 1 else "\u274c"
            print(f"    {si} [{s}/2] {note}")"""

E3_NEW = """        print(f"  Score detalhe:")
        for k, note in c['score_notes'].items():
            s  = c['score_detail'][k]
            si = "\u2705" if s == 2 else "\u26a0" if s == 1 else "\u274c"
            print(f"    {si} [{s}/2] {note}")

        cf = c.get('capital_fit')
        if cf:
            _cfi  = {"APROVO_CAPITAL": "\U0001F7E2", "MONITORAR": "\U0001F7E1",
                     "REPROVO_CAPITAL": "\U0001F534", "DADOS_INSUFICIENTES": "\u26AA"}
            ic    = _cfi.get(cf.get('capital_status', ''), '')
            cost  = f"${cf['contract_cost']:.0f}" if cf.get('contract_cost') is not None else "N/A"
            risk  = f"${cf['risk_at_stop']:.0f}"  if cf.get('risk_at_stop')  is not None else "N/A"
            print(f"  Capital Fit:")
            print(f"    {ic} {cf.get('capital_status','')} | Bucket: {cf.get('cost_bucket','')}")
            print(f"    Custo: {cost} | Risco no stop (35%): {risk} | Estrutura: {cf.get('preferred_structure','')}")
            print(f"    Nota: {cf.get('rosi_note','')}")"""


def main():
    print("patch_capital_fit_v2.py — Capital Fit no terminal do scanner\n")
    if not SCANNER.exists():
        print("ERRO: us_swing_ibkr.py nao encontrado. Rode de dentro de ~/RBC.")
        sys.exit(1)
    text = SCANNER.read_text(encoding='utf-8')
    if "enrich_scan_results" not in text:
        print("ERRO: patch v1 nao aplicado neste arquivo. Rode patch_capital_fit.py antes.")
        sys.exit(1)

    dst = SCANNER.with_name(f"{SCANNER.stem}_backup_{TS}.py")
    shutil.copy2(SCANNER, dst)
    print(f"  backup: {dst.name}\n")

    apply(SCANNER, E1_OLD, E1_NEW, "E1 (enriquecer antes do print)", "enrich_scan_results([r])")
    apply(SCANNER, E2_OLD, E2_NEW, "E2 (remover bloco redundante)", "__nunca_marca__" )
    apply(SCANNER, E3_OLD, E3_NEW, "E3 (bloco no terminal)", "Capital Fit:\")")

    import py_compile
    py_compile.compile(str(SCANNER), doraise=True)
    print("\n  us_swing_ibkr.py: sintaxe OK")
    print("""
Pronto. Proximo scan mostra o Capital Fit no terminal, abaixo do Score detalhe.
  git add us_swing_ibkr.py patch_capital_fit_v2.py
  git commit -m "Modo 5: Capital Fit no output do terminal (validacao GPT item 3)"
  git push
""")


if __name__ == '__main__':
    main()
