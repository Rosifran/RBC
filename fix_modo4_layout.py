with open('templates/index.html', 'r') as f:
    c = f.read()

# Fix 1: data sem timezone
old1 = """const raw = (r.date||'').substring(0,10);
        const [y,m,d] = raw.split('-');
        const dt = d+'/'+m+'/'+y;"""
new1 = """const parts = (r.date||'').substring(0,10).split('-');
        const dt = parts.length===3 ? parts[2]+'/'+parts[1]+'/'+parts[0] : r.date;"""

if old1 in c:
    c = c.replace(old1, new1)
    print("OK date")
else:
    # Pode estar com new Date ainda
    old1b = "const dt = new Date(r.date).toLocaleDateString('pt-BR');"
    new1b = """const parts = (r.date||'').substring(0,10).split('-');
        const dt = parts.length===3 ? parts[2]+'/'+parts[1]+'/'+parts[0] : r.date;"""
    if old1b in c:
        c = c.replace(old1b, new1b)
        print("OK date (fallback)")
    else:
        print("ERRO date")

# Fix 2: tabela com scroll visivel e Path truncado
old2 = "let html = '<div style=\"overflow-x:auto;-webkit-overflow-scrolling:touch;\"><table style=\"width:100%;border-collapse:collapse;font-size:10px;white-space:nowrap;\">';"
new2 = "let html = '<div style=\"overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #e2e8f0;border-radius:8px;\"><table style=\"border-collapse:collapse;font-size:10px;white-space:nowrap;min-width:900px;\">';"

if old2 in c:
    c = c.replace(old2, new2)
    print("OK table wrapper")
else:
    old2b = "let html = '<div style=\"overflow-x:auto;\"><table style=\"width:100%;border-collapse:collapse;font-size:11px;\">';"
    new2b = "let html = '<div style=\"overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid #e2e8f0;border-radius:8px;\"><table style=\"border-collapse:collapse;font-size:10px;white-space:nowrap;min-width:900px;\">';"
    if old2b in c:
        c = c.replace(old2b, new2b)
        print("OK table wrapper (fallback)")
    else:
        print("ERRO table wrapper")

# Fix 3: Path com largura fixa e truncado
old3 = "html += '<td style=\"padding:5px 8px;color:#475569;font-size:10px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;\" title=\"'+(r.trade_path||'')+'\">'+( r.trade_path||'-')+'</td>';"
new3 = "html += '<td style=\"padding:4px 6px;color:#475569;font-size:10px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;\" title=\"'+(r.trade_path||'')+'\">'+( r.trade_path||'-')+'</td>';"

if old3 in c:
    c = c.replace(old3, new3)
    print("OK path width")
else:
    print("SKIP path width")

with open('templates/index.html', 'w') as f:
    f.write(c)
