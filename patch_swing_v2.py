"""
RBC — Patch Swing v2: Edge Direcional + Verdict Integrado + Invalidacao
========================================================================
Corrige as 3 falhas encontradas na revisao de 11/06 (caso NVDA):

F1. edge_summary: neutros contavam como favoraveis e Skew/PC nao eram
    direcionais → CALL e PUT aprovavam juntos.
    Fix: Skew e P/C espelhados por direcao; favoravel = somente score 2;
    FAVORAVEL exige 2+ a favor, NENHUM contra e ao menos 1 fator
    DIRECIONAL (Skew ou P/C) a favor — ambiente bom sem direcao nao aprova.

F2. overall_verdict ignorava o edge — "APROVO" media so a qualidade do
    contrato (delta/spread/liquidez).
    Fix: APROVO exige contrato >= 8 E edge FAVORAVEL.
    Edge NEUTRO trava em AGUARDAR. Edge DESFAVORAVEL = REPROVO.

F3. Nenhuma invalidacao de tese declarada.
    Fix: invalid_level = spot -/+ 0.5 x move semanal esperado (IV que o
    scanner ja tem). Aparece no resultado e no print.

NAO altera: calc_gex/vrp/skew/net_gex/pc (funcoes de calculo intactas),
score_contract, stops/alvos de premio, busca TWS, save dos scans.

Uso: python3 patch_swing_v2.py ~/RBC/us_swing_ibkr.py
"""
import sys, shutil, ast
from datetime import datetime

# 1. edge_summary — miolo direcional
A1_OLD = '''    scores    = [gex['score'], vrp['score'], skew['score'], pc['score']]
    aprovados = sum(1 for s in scores if s >= 1)

    # Ajuste de direcao
    skew_val = skew.get('skew_pct') or 0
    if direction == 'CALL' and skew_val > 5:
        aprovados -= 1
    if direction == 'PUT' and skew_val < -5:
        aprovados -= 1

    if aprovados >= 3:
        verdict = "EDGE FAVORAVEL"
        note    = f"{aprovados}/4 fatores alinham para {direction}"
    elif aprovados == 2:
        verdict = "EDGE NEUTRO"
        note    = f"Apenas {aprovados}/4 fatores alinham — aguardar confirmacao"
    else:
        verdict = "EDGE DESFAVORAVEL"
        note    = f"Apenas {aprovados}/4 fatores alinham — evitar entrada"'''

A1_NEW = '''    # ── Edge direcional v2 ─────────────────────────────────────────────
    # VRP e GEX: nao-direcionais (custo da vol e regime) — score original.
    # Skew e P/C: DIRECIONAIS — pontuam contra/a favor da direcao pedida.
    # Favoravel = somente score 2. Neutro (1) NAO conta como favoravel.
    skew_val = skew.get('skew_pct')
    pc_val   = pc.get('pc_ratio')

    if skew_val is None:
        skew_s = 1
    elif direction == 'CALL':
        # bearish forte contra (0) | bearish leve (1) | neutro (1) | bullish flow a favor (2)
        skew_s = 0 if skew_val > 5 else (1 if skew_val > -2 else 2)
    else:  # PUT — espelho
        skew_s = 0 if skew_val < -5 else (1 if skew_val < 2 else 2)

    if pc_val is None:
        pc_s = 1
    elif direction == 'CALL':
        pc_s = 2 if pc_val < 0.7 else (0 if pc_val > 1.2 else 1)
    else:  # PUT — espelho
        pc_s = 2 if pc_val > 1.2 else (0 if pc_val < 0.7 else 1)

    scores         = [gex['score'], vrp['score'], skew_s, pc_s]
    favoraveis     = sum(1 for s in scores if s == 2)
    zeros          = sum(1 for s in scores if s == 0)
    dir_favoraveis = sum(1 for s in (skew_s, pc_s) if s == 2)  # so Skew/PC carregam direcao
    aprovados      = favoraveis

    if favoraveis >= 2 and zeros == 0 and dir_favoraveis >= 1:
        verdict = "EDGE FAVORAVEL"
        note    = f"{favoraveis}/4 fatores claramente a favor de {direction}, nenhum contra"
    elif zeros >= 2 or favoraveis == 0:
        verdict = "EDGE DESFAVORAVEL"
        note    = f"{zeros} fator(es) contra {direction} — evitar entrada"
    else:
        verdict = "EDGE NEUTRO"
        note    = (f"{favoraveis}/4 a favor ({dir_favoraveis} direcional), {zeros} contra "
                   f"{direction} — sem edge claro, aguardar confirmacao")'''

# 2. Verdict integrado + invalidação no scan_ticker
A2_OLD = '''    best    = top3[0]['score'] if top3 else 0
    overall = "APROVO" if best >= 8 else "AGUARDAR" if best >= 6 else "REPROVO"

    return {
        "ticker":          ticker,
        "direction":       direction,
        "spot":            spot,
        "scanned":         len(chain_dir),
        "overall_verdict": overall,
        "edge":            edge,
        "top_contracts":   top3,
        "timestamp":       datetime.now().strftime('%Y-%m-%d %H:%M ET'),
    }'''

A2_NEW = '''    best = top3[0]['score'] if top3 else 0

    # ── Verdict integrado: contrato bom NAO basta — precisa de edge ───
    _ev = edge.get('verdict', '')
    if "DESFAVORAVEL" in _ev:
        overall      = "REPROVO"
        overall_note = f"Edge contra {direction} — contrato bom nao salva direcao ruim."
    elif "INCOMPLETO" in _ev:
        overall      = "AGUARDAR"
        overall_note = "Edge incompleto — rodar com mercado aberto antes de decidir."
    elif "NEUTRO" in _ev:
        overall      = "AGUARDAR" if best >= 6 else "REPROVO"
        overall_note = f"Contrato {best}/10 mas SEM edge direcional — aguardar definicao."
    else:  # FAVORAVEL
        overall      = "APROVO" if best >= 8 else "AGUARDAR" if best >= 6 else "REPROVO"
        overall_note = f"Edge a favor de {direction} + contrato {best}/10."

    # ── Invalidacao da tese (nivel do subjacente) ──────────────────────
    invalid_level = None
    invalid_note  = None
    _iv = snap.get('iv_ann') or 0
    if spot and _iv:
        _wk_move = spot * _iv * (7 / 365) ** 0.5
        if direction == 'PUT':
            invalid_level = round(spot + 0.5 * _wk_move, 2)
            invalid_note  = f"PUT invalida se {ticker} fechar ACIMA de ${invalid_level}"
        else:
            invalid_level = round(spot - 0.5 * _wk_move, 2)
            invalid_note  = f"CALL invalida se {ticker} fechar ABAIXO de ${invalid_level}"

    return {
        "ticker":          ticker,
        "direction":       direction,
        "spot":            spot,
        "scanned":         len(chain_dir),
        "overall_verdict": overall,
        "overall_note":    overall_note,
        "invalid_level":   invalid_level,
        "invalid_note":    invalid_note,
        "edge":            edge,
        "top_contracts":   top3,
        "timestamp":       datetime.now().strftime('%Y-%m-%d %H:%M ET'),
    }'''

# 3. Print: nota do verdict
A3_OLD = '''    print(f"  {icon} {r['overall_verdict']} — {r['scanned']} contratos escaneados")'''

A3_NEW = '''    print(f"  {icon} {r['overall_verdict']} — {r['scanned']} contratos escaneados")
    if r.get('overall_note'):
        print(f"     {r['overall_note']}")'''

# 4. Print: invalidação junto dos alvos
A4_OLD = '''        print(f"  Alvo 2     : ${c['target_2']:.2f}  (+80%)")'''

A4_NEW = '''        print(f"  Alvo 2     : ${c['target_2']:.2f}  (+80%)")
        if r.get('invalid_note'):
            print(f"  Invalidacao: {r['invalid_note']}")'''

# ══════════════════════════════════════════════════════════════════════
if len(sys.argv) < 2:
    print("Uso: python3 patch_swing_v2.py ~/RBC/us_swing_ibkr.py")
    sys.exit(1)

path = sys.argv[1]
patches = [
    (A1_OLD, A1_NEW, "edge_summary direcional v2"),
    (A2_OLD, A2_NEW, "verdict integrado + invalidacao"),
    (A3_OLD, A3_NEW, "print: nota do verdict"),
    (A4_OLD, A4_NEW, "print: invalidacao"),
]

content = open(path).read()
for old, _, label in patches:
    n = content.count(old)
    if n != 1:
        print(f"ERRO — '{label}': ancora encontrada {n}x")
        sys.exit(1)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".py", f"_backup_{ts}.py"))
print(f"Backup criado ({ts})")

for old, new, label in patches:
    content = content.replace(old, new, 1)
    print(f"✅ {label}")

ast.parse(content)
open(path, 'w').write(content)
print()
print("TESTE DE PRODUCAO (validacao comparativa):")
print("  python3 ~/RBC/us_swing_ibkr.py")
print("  → NVDA: CALL e PUT NAO devem mais aprovar juntos")
print("  → cada linha deve mostrar a nota do edge e a Invalidacao")
print()
print("  git add us_swing_ibkr.py")
print('  git commit -m "APROVADO: Swing v2 — edge direcional, verdict integrado, invalidacao"')
print("  git push")
