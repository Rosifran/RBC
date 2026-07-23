"""
RBC EUA — patch TradingView quote endpoint
Adiciona:
  POST /api/tv/quote  — recebe SPY e VIX do TradingView
  GET  /api/tv/quote  — retorna último valor recebido

Salva em memória (Railway reinicia limpo — mas Modo 2 tem fallback manual).
Não toca em nenhuma lógica existente.
Uso: python3 patch_tv_quote.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

# Insere logo após os imports/configurações, antes da primeira rota
OLD_ANCHOR = '@app.route("/api/modo1", methods=["POST"])'

NEW_CODE = '''# ── TradingView market quote (SPY + VIX) ─────────────────────────────
_tv_quote = {}  # {"spy": float, "vix": float, "ts": str}

@app.route("/api/tv/quote", methods=["POST"])
def tv_quote_post():
    """
    Recebe quote de mercado do TradingView.
    Payload esperado: {"symbol": "SPY"|"VIX", "price": 756.10, "time": "2026-06-08T10:05:00"}
    """
    data   = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).upper().replace("$", "")
    price  = data.get("price")
    ts     = data.get("time") or datetime.utcnow().isoformat()

    if not symbol or price is None:
        return jsonify({"error": "symbol and price required"}), 400

    try:
        price = float(price)
    except (ValueError, TypeError):
        return jsonify({"error": "price must be numeric"}), 400

    if symbol in ("SPY", "SPDR"):
        _tv_quote["spy"] = price
    elif symbol in ("VIX", "CBOE:VIX", "VIX1D"):
        _tv_quote["vix"] = price
    else:
        return jsonify({"error": f"unknown symbol: {symbol}"}), 400

    _tv_quote["ts"] = ts
    return jsonify({"ok": True, "symbol": symbol, "price": price, "ts": ts})


@app.route("/api/tv/quote", methods=["GET"])
def tv_quote_get():
    """Retorna o último quote recebido do TradingView."""
    if not _tv_quote:
        return jsonify({"ok": False, "message": "Sem dados recentes — preencher manualmente."}), 200
    age_ok = True
    if _tv_quote.get("ts"):
        try:
            from datetime import timezone
            ts = datetime.fromisoformat(_tv_quote["ts"].replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            age_ok = age_min < 30  # considera stale após 30 min
        except Exception:
            pass
    return jsonify({
        "ok":     True,
        "spy":    _tv_quote.get("spy"),
        "vix":    _tv_quote.get("vix"),
        "ts":     _tv_quote.get("ts"),
        "fresh":  age_ok,
        "message": None if age_ok else "Dado com mais de 30 min — confirmar manualmente.",
    })


@app.route("/api/modo1", methods=["POST"])'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_tv_quote.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

if OLD_ANCHOR not in content:
    print("ERRO — âncora não encontrada. Verifique o arquivo.")
    sys.exit(1)

if "_tv_quote" in content:
    print("AVISO — endpoint já existe. Nada foi alterado.")
    sys.exit(0)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.replace(".py", f"_backup_{ts}.py")
shutil.copy2(path, backup)
print(f"Backup criado: {backup}")

content = content.replace(OLD_ANCHOR, NEW_CODE, 1)
ast.parse(content)
open(path, 'w').write(content)
print("✅ Endpoints adicionados:")
print("   POST /api/tv/quote  — recebe SPY ou VIX do TradingView")
print("   GET  /api/tv/quote  — retorna último valor (fresh/stale)")
print()
print("Configurar no TradingView — URL do webhook:")
print("  https://web-production-00b33.up.railway.app/api/tv/quote")
print()
print("Payload para alerta SPY:")
print('  {"symbol": "SPY", "price": "{{close}}", "time": "{{time}}"}')
print()
print("Payload para alerta VIX:")
print('  {"symbol": "VIX", "price": "{{close}}", "time": "{{time}}"}')
