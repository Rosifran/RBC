"""
RBC — Risk Bridge Capital | Flask Backend v1.0
"""
from flask import Flask, request, jsonify
import os, sys

app = Flask(__name__)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from rbc_0dte_scanner import parse_sg_data, opening_watch, analyze_spy_0dte
    SCANNER_OK = True
except Exception as e:
    SCANNER_OK = False
    SCANNER_ERR = str(e)

@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'RBC backend', 'status': 'healthy', 'scanner': 'ok' if SCANNER_OK else SCANNER_ERR})

@app.route('/api/modo1', methods=['POST'])
def modo1():
    try:
        raw = request.get_json().get('sg_string', '')
        if not raw: return jsonify({'error': 'sg_string vazio'}), 400
        sg = parse_sg_data(raw)
        spy = sg.get('SPY', {})
        if not spy: return jsonify({'error': 'SPY não encontrado'}), 400
        return jsonify({'ok': True, 'spy': {'call_wall': spy.get('call_wall'), 'put_wall': spy.get('put_wall'), 'zero_gamma': spy.get('zero_gamma'), 'vol_trigger': spy.get('vol_trigger'), 'abs_gamma': spy.get('abs_gamma'), 'move_1d': spy.get('imp_1d'), 'combos': spy.get('combos', [])}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/modo2', methods=['POST'])
def modo2():
    try:
        d = request.get_json()
        vix_open, vix_now = float(d['vix_open']), float(d['vix_now'])
        spy_open, spy_now = float(d['spy_open']), float(d['spy_now'])
        sg = parse_sg_data(d.get('sg_string', '')) if d.get('sg_string') else {}
        spy_ref = sg.get('SPY', {})
        score_h = 0
        vix_d = vix_now - vix_open
        spot_d = spy_now - spy_open
        above_zg = spy_ref.get('zero_gamma') and spy_now > spy_ref['zero_gamma']
        above_vt = spy_ref.get('vol_trigger') and spy_now > spy_ref['vol_trigger']
        if spot_d > 0.5 and vix_d < 0: score_h += 3
        elif spot_d > 0.3 and vix_d < 0: score_h += 2
        elif spot_d < -0.5 and vix_d > 0: score_h -= 3
        elif spot_d > 0.5 and vix_d > 0.5: score_h -= 1
        if above_zg and above_vt: score_h += 2
        elif above_zg: score_h += 1
        elif not above_zg: score_h -= 2
        hiro = 'positive' if score_h >= 4 else 'negative' if score_h <= -3 else 'neutral'
        ow = opening_watch(vix_open, vix_now, hiro, spy_open, spy_now, sg)
        return jsonify({'ok': True, 'verdict': ow['verdict'], 'score': ow['score'], 'hiro': hiro, 'signals': [{'icon': s[0], 'title': s[1], 'desc': s[2]} for s in ow.get('signals', [])]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/modo3', methods=['POST'])
def modo3():
    try:
        d = request.get_json()
        spot = float(d['spot'])
        iv   = float(d['iv']) / 100
        premio = float(d['premio']) if d.get('premio') else None
        sg = parse_sg_data(d.get('sg_string', '')) if d.get('sg_string') else {}
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
        except:
            now_et = datetime.now()
        close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        hours = max(0.25, (close - now_et).seconds / 3600)
        result = analyze_spy_0dte(sg, spot, iv, 0.0527, hours, 50000, premio, 1)
        if 'error' in result: return jsonify({'error': result['error']}), 400
        best  = result['candidates'][0] if result.get('candidates') else None
        exits = result.get('exits')
        gate  = result.get('gate', {})
        return jsonify({'ok': True, 'gate_open': gate.get('gate_open', False), 'best_side': result.get('best_side'), 'strike': {'type': best['type'], 'strike': best['strike'], 'price': round(best['price'], 2), 'delta': round(best['delta'], 4)} if best else None, 'exits': {'premium_paid': round(exits['premium_paid'], 2), 'target_price': round(exits['target_price'], 2), 'target_usd': round(exits['target_usd'], 2), 'stop_price': round(exits['stop_price'], 2), 'stop_usd': round(exits['stop_usd'], 2)} if exits else None, 'hours': round(hours, 1)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)

@app.route('/')
def index():
    from flask import render_template
    return render_template('index.html')
