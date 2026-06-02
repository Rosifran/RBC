with open('app.py', 'r') as f:
    c = f.read()

start = c.find('@app.route("/api/webhook", methods=["POST"])')
end   = c.find('\n@app.route("/api/save-snapshot"', start)

if start < 0 or end < 0:
    print("ERRO func nao encontrada start=%d end=%d" % (start, end))
else:
    new_func = '''@app.route("/api/webhook", methods=["POST"])
def tradingview_webhook():
    """Recebe eventos do TradingView e atualiza o journal do dia."""
    data  = request.get_json(silent=True) or {}
    event = data.get("event")
    date  = data.get("date")
    time  = data.get("time")

    if not event:
        return jsonify({"error": "event required"}), 400

    try:
        from journal import save_snapshot, get_snapshot_by_date
        update = {"date": date} if date else {}

        if event == "c4_reclaimed":
            update.update({"c4_reclaimed": True, "c4_reclaimed_time": time})
        elif event == "c1_hit":
            update.update({"c1_hit": True, "c1_hit_time": time})
        elif event == "call_wall_hit":
            update.update({"call_wall_hit": True, "call_wall_hit_time": time})
        elif event == "near_call_wall":
            update.update({"near_call_wall": True})
        elif event == "vol_trigger_lost":
            update.update({"vol_trigger_lost": True, "vol_trigger_lost_time": time})
        elif event == "close_day":
            high  = float(data.get("high")  or 0)
            low   = float(data.get("low")   or 0)
            open_ = float(data.get("open")  or 0)
            close = float(data.get("close") or 0)

            update.update({
                "open_spy":  open_ or None,
                "close_spy": close or None,
                "max_spy":   high  or None,
                "min_spy":   low   or None,
            })

            row0 = get_snapshot_by_date(date) if date else {}
            c4_level  = float(row0.get("c4")          or 0)
            c1_level  = float(row0.get("c1")          or 0)
            cw_level  = float(row0.get("call_wall")   or 0)
            vt_level  = float(row0.get("vol_trigger") or 0)

            if not (c4_level and c1_level and cw_level and vt_level):
                return jsonify({"error": "Niveis nao encontrados para %s. Processe o PDF no Modo 1 primeiro." % date}), 400

            c4_rec  = high >= c4_level
            c1_hit  = high >= c1_level
            cw_hit  = high >= cw_level
            near_cw = high >= (cw_level - 0.25)
            vt_lost = low  <= vt_level

            update.update({
                "c4_reclaimed":       c4_rec,
                "c1_hit":             c1_hit,
                "call_wall_hit":      cw_hit,
                "near_call_wall":     near_cw,
                "vol_trigger_lost":   vt_lost,
            })

            path_parts = []
            if open_ and vt_level and c4_level and vt_level <= open_ <= c4_level:
                path_parts.append("compression")
            if c4_rec:   path_parts.append("c4")
            if c1_hit:   path_parts.append("c1")
            if cw_hit:   path_parts.append("call_wall")
            elif near_cw: path_parts.append("near_call_wall")
            if vt_lost:  path_parts.append("vol_trigger_lost")
            if path_parts:
                update["trade_path"] = " -> ".join(path_parts)

        row = save_snapshot(update)
        return jsonify({"ok": True, "event": event, "date": str(row["date"]), "update": {k:v for k,v in update.items() if k != "date"}})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

'''
    c = c[:start] + new_func + c[end:]
    with open('app.py', 'w') as f:
        f.write(c)
    print("OK webhook v2")
