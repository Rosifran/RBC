#!/usr/bin/env python3
"""
RBC — Registro manual de trades
===============================
    python3 rbc_trade.py            entrada (registrar novo trade)
    python3 rbc_trade.py --saida    fechar um trade aberto
    python3 rbc_trade.py --abertos  listar trades em aberto
    python3 rbc_trade.py --resumo   estatísticas do período
    python3 rbc_trade.py --sinais   últimos sinais gravados
"""

import sys
from rbc_log import (
    log_trade_entry, log_trade_exit, open_trades,
    read_rows, SIGNALS_CSV, SIGNAL_COLS, TRADES_CSV, TRADE_COLS,
)

LINHA = "=" * 62


def ask(label, default="", obrigatorio=False):
    suf = f" [{default}]" if default else ""
    while True:
        v = input(f"  {label}{suf}: ").strip()
        if not v and default:
            return default
        if v or not obrigatorio:
            return v
        print("    ⚠ campo obrigatório")


def ask_num(label, default="", obrigatorio=False):
    while True:
        v = ask(label, default, obrigatorio)
        if v == "":
            return v
        try:
            float(v)
            return v
        except ValueError:
            print("    ⚠ digite um número")


# ============================================================
def cmd_entrada():
    print(f"\n{LINHA}\n  REGISTRAR ENTRADA\n{LINHA}\n")

    sinais = read_rows(SIGNALS_CSV, SIGNAL_COLS)[-8:]
    if sinais:
        print("  Últimos sinais:")
        for s in sinais:
            print(f"    {s['signal_id']}  {s['timestamp_et'][:16]}  "
                  f"{s['modulo']:6s} {s['ticker']:5s} {s['gate_status']}")
        print()

    signal_id  = ask("signal_id (vazio se avulso)")
    modulo     = ask("modulo (0DTE/SWING)", "SWING", True).upper()
    ticker     = ask("ticker", obrigatorio=True).upper()
    tipo       = ask("tipo (CALL/PUT/SPREAD)", "CALL", True).upper()
    strike     = ask("strike", obrigatorio=True)
    vencimento = ask("vencimento (YYYY-MM-DD)", obrigatorio=True)
    qty        = ask_num("qty (contratos)", "1", True)
    fill       = ask_num("fill de ENTRADA (prêmio pago/recebido)", obrigatorio=True)
    bid        = ask_num("bid no momento (opcional)")
    aski       = ask_num("ask no momento (opcional)")
    nota       = ask("nota (opcional)")

    tid = log_trade_entry(signal_id, modulo, ticker, tipo, strike, vencimento,
                          qty, fill, bid, aski, nota)

    custo = float(fill) * 100 * int(float(qty))
    print(f"\n  ✅ {tid} registrado — custo total US$ {custo:.2f}\n")


# ============================================================
def cmd_saida():
    print(f"\n{LINHA}\n  REGISTRAR SAÍDA\n{LINHA}\n")

    abertos = open_trades()
    if not abertos:
        print("  Nenhum trade em aberto.\n")
        return

    for t in abertos:
        print(f"    {t['trade_id']}  {t['ticker']:5s} {t['tipo']:5s} "
              f"{t['strike']:>7s}  venc {t['vencimento']}  "
              f"qty {t['qty']}  entrada {t['fill_entrada']}")
    print()

    tid    = ask("trade_id", obrigatorio=True).upper()
    fill   = ask_num("fill de SAÍDA", obrigatorio=True)
    bid    = ask_num("bid no momento (opcional)")
    aski   = ask_num("ask no momento (opcional)")
    motivo = ask("motivo (ALVO/STOP/TEMPO/MANUAL/EXPIROU)", "ALVO", True).upper()
    nota   = ask("nota (opcional)")

    ok = log_trade_exit(tid, fill, bid, aski, motivo, nota)
    if not ok:
        print(f"\n  ⚠ trade_id {tid} não encontrado.\n")
        return

    r = [x for x in read_rows(TRADES_CSV, TRADE_COLS) if x["trade_id"] == tid][0]
    sinal = "🟢" if float(r["resultado_usd"]) >= 0 else "🔴"
    print(f"\n  {sinal} {tid} fechado — "
          f"US$ {r['resultado_usd']} ({r['resultado_pct']}%)\n")


# ============================================================
def cmd_abertos():
    abertos = open_trades()
    print(f"\n{LINHA}\n  TRADES EM ABERTO ({len(abertos)})\n{LINHA}\n")
    if not abertos:
        print("  Nenhum.\n")
        return
    for t in abertos:
        custo = float(t["fill_entrada"]) * 100 * int(t["qty"])
        print(f"  {t['trade_id']}  {t['modulo']:6s} {t['ticker']:5s} {t['tipo']:5s} "
              f"{t['strike']:>7s}  venc {t['vencimento']}")
        print(f"           entrada {t['data_entrada']} {t['hora_et_entrada'][:5]} ET  "
              f"@ {t['fill_entrada']}  x{t['qty']}  = US$ {custo:.2f}\n")


# ============================================================
def cmd_resumo():
    trades  = read_rows(TRADES_CSV, TRADE_COLS)
    sinais  = read_rows(SIGNALS_CSV, SIGNAL_COLS)
    fechados = [t for t in trades if t.get("resultado_usd")]

    print(f"\n{LINHA}\n  RESUMO DO PERÍODO\n{LINHA}\n")
    print(f"  Sinais gravados   : {len(sinais)}")
    print(f"  Trades executados : {len(trades)}")
    print(f"  Fechados          : {len(fechados)}")
    print(f"  Em aberto         : {len(trades) - len(fechados)}")

    if not fechados:
        print()
        return

    res    = [float(t["resultado_usd"]) for t in fechados]
    wins   = [r for r in res if r > 0]
    losses = [r for r in res if r <= 0]
    total  = sum(res)

    print(f"\n  Resultado total   : US$ {total:,.2f}")
    print(f"  Win rate          : {len(wins)/len(res)*100:.1f}%  "
          f"({len(wins)}W / {len(losses)}L)")
    if wins:
        print(f"  Ganho médio       : US$ {sum(wins)/len(wins):,.2f}")
    if losses:
        print(f"  Perda média       : US$ {sum(losses)/len(losses):,.2f}")
    if wins and losses:
        pf = sum(wins) / abs(sum(losses))
        print(f"  Profit factor     : {pf:.2f}")
    print(f"  Melhor trade      : US$ {max(res):,.2f}")
    print(f"  Pior trade        : US$ {min(res):,.2f}")

    # por módulo
    print(f"\n  Por módulo:")
    for mod in sorted({t["modulo"] for t in fechados}):
        sub = [float(t["resultado_usd"]) for t in fechados if t["modulo"] == mod]
        w   = len([r for r in sub if r > 0])
        print(f"    {mod:6s}  {len(sub):2d} trades  "
              f"US$ {sum(sub):>9,.2f}  win {w/len(sub)*100:.0f}%")

    # cenário pessimista (entrada no ask, saída no bid)
    pess = []
    for t in fechados:
        try:
            e = float(t["ask_entrada"]) if t["ask_entrada"] else float(t["fill_entrada"])
            s = float(t["bid_saida"])   if t["bid_saida"]   else float(t["fill_saida"])
            pess.append((s - e) * 100 * int(t["qty"]))
        except (ValueError, TypeError):
            pass
    if pess and len(pess) == len(fechados):
        print(f"\n  Cenário pessimista (entrada no ask / saída no bid):")
        print(f"    Resultado       : US$ {sum(pess):,.2f}")
        print(f"    Diferença       : US$ {sum(pess) - total:,.2f}")
    print()


# ============================================================
def cmd_sinais():
    sinais = read_rows(SIGNALS_CSV, SIGNAL_COLS)[-20:]
    print(f"\n{LINHA}\n  ÚLTIMOS SINAIS\n{LINHA}\n")
    if not sinais:
        print("  Nenhum sinal gravado ainda.\n")
        return
    for s in sinais:
        print(f"  {s['signal_id']}  {s['timestamp_et'][:16]}  {s['modulo']:6s} "
              f"{s['ticker']:5s} {s['gate_status']:10s} {s['estrategia']}")
    print()


# ============================================================
if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if   arg == "--saida":   cmd_saida()
        elif arg == "--abertos": cmd_abertos()
        elif arg == "--resumo":  cmd_resumo()
        elif arg == "--sinais":  cmd_sinais()
        else:                    cmd_entrada()
    except KeyboardInterrupt:
        print("\n\n  Cancelado.\n")
