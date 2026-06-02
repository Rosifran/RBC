with open('templates/index.html', 'r') as f:
    c = f.read()

# Adicionar overflow-x:auto no wrapper e font-size menor
old = "let html = '<div style=\"overflow-x:auto;\"><table style=\"width:100%;border-collapse:collapse;font-size:11px;\">';"
new = "let html = '<div style=\"overflow-x:auto;-webkit-overflow-scrolling:touch;\"><table style=\"width:100%;border-collapse:collapse;font-size:10px;white-space:nowrap;\">';"

if old in c:
    c = c.replace(old, new)
    print("OK scroll")
else:
    print("ERRO scroll")

# Padding menor nas celulas
old2 = "['Data','Day','Score','Open','Close','Max','Min','Decisao','Path','C4','C1','CW','VT Lost','Quality'].forEach(h => {\n        html += '<th style=\"padding:6px 8px;color:#64748b;font-weight:700;text-align:left;\">'+h+'</th>';"
new2 = "['Data','Day','Score','Open','Close','Max','Min','Decisao','Path','C4','C1','CW','VT Lost','Quality'].forEach(h => {\n        html += '<th style=\"padding:4px 6px;color:#64748b;font-weight:700;text-align:left;white-space:nowrap;\">'+h+'</th>';"

if old2 in c:
    c = c.replace(old2, new2)
    print("OK header padding")
else:
    print("ERRO header padding")

with open('templates/index.html', 'w') as f:
    f.write(c)
