with open('templates/index.html', 'r') as f:
    c = f.read()

start = c.find('  async function loadJournal() {')
end   = c.find('  async function saveJournalNotes()', start)

if start < 0 or end < 0:
    print("ERRO func nao encontrada start=%d end=%d" % (start, end))
else:
    new_func = """  async function loadJournal() {
    const el = document.getElementById('journal-table');
    if (!el) return;
    try {
      const res  = await fetch('/api/journal?limit=30');
      const rows = await res.json();
      if (!rows.length) { el.innerHTML = '<p style="font-size:12px;color:#94a3b8;">Nenhum registro ainda.</p>'; return; }
      const decColor = d => (d||'').includes('CALL') ? '#16a34a' : (d||'').includes('PUT') ? '#dc2626' : (d||'')==='NO TRADE' ? '#64748b' : '#475569';
      const scoreColor = s => !s ? '#f1f5f9' : s<=2 ? '#fee2e2' : s>=4 ? '#dcfce7' : '#fef9c3';
      let html = '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:11px;">';
      html += '<thead><tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">';
      ['Data','Day','Score','Open','Close','Max','Min','Decisao','Path','C4','C1','CW','VT Lost','Quality'].forEach(h => {
        html += '<th style="padding:6px 8px;color:#64748b;font-weight:700;text-align:left;">'+h+'</th>';
      });
      html += '</tr></thead><tbody>';
      rows.forEach(r => {
        const dt = new Date(r.date).toLocaleDateString('pt-BR');
        const sc = r.pdf_score;
        const c4 = r.c4_reclaimed ? ('\u2705 ' + (r.c4||'')) : '\u274c';
        const c1 = r.c1_hit ? ('\u2705 ' + (r.c1||'')) : '\u274c';
        const cw = r.call_wall_hit ? ('\u2705 '+(r.call_wall||'')) : r.near_call_wall ? ('~ '+(r.call_wall||'')) : '\u274c';
        const vt = r.vol_trigger_lost ? '\u26a0\ufe0f YES' : '\u2014';
        html += '<tr style="border-bottom:1px solid #f1f5f9;">';
        html += '<td style="padding:5px 8px;font-weight:600;white-space:nowrap;">'+dt+'</td>';
        html += '<td style="padding:5px 8px;color:#64748b;">'+(r.weekday||'-')+'</td>';
        html += '<td style="padding:5px 8px;text-align:center;"><span style="background:'+scoreColor(sc)+';padding:2px 6px;border-radius:4px;font-weight:700;">'+(sc ? sc+'/5' : '-')+'</span></td>';
        html += '<td style="padding:5px 8px;">'+(r.open_spy||'-')+'</td>';
        html += '<td style="padding:5px 8px;">'+(r.close_spy||'-')+'</td>';
        html += '<td style="padding:5px 8px;color:#16a34a;font-weight:600;">'+(r.max_spy||'-')+'</td>';
        html += '<td style="padding:5px 8px;color:#dc2626;font-weight:600;">'+(r.min_spy||'-')+'</td>';
        html += '<td style="padding:5px 8px;font-weight:700;color:'+decColor(r.modo2_decision)+';font-size:10px;white-space:nowrap;">'+(r.modo2_decision||'-')+'</td>';
        html += '<td style="padding:5px 8px;color:#475569;font-size:10px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+(r.trade_path||'')+'">'+(r.trade_path||'-')+'</td>';
        html += '<td style="padding:5px 8px;text-align:center;">'+c4+'</td>';
        html += '<td style="padding:5px 8px;text-align:center;">'+c1+'</td>';
        html += '<td style="padding:5px 8px;text-align:center;">'+cw+'</td>';
        html += '<td style="padding:5px 8px;text-align:center;">'+vt+'</td>';
        html += '<td style="padding:5px 8px;color:#475569;font-size:10px;">'+(r.trade_quality||'-')+'</td>';
        html += '</tr>';
      });
      html += '</tbody></table></div>';
      el.innerHTML = html;
    } catch(e) {
      el.innerHTML = '<p style="color:#dc2626;font-size:12px;">Erro ao carregar journal.</p>';
    }
  }

"""
    c = c[:start] + new_func + c[end:]
    with open('templates/index.html', 'w') as f:
        f.write(c)
    print("OK")
