with open('templates/index.html', 'r') as f:
    c = f.read()

c = c.replace(
    "const vt = r.hit_stop ? 'YES' : '-';",
    "const vt = r.vol_trigger_lost ? '\u26a0\ufe0f YES' : '\u2014';"
)

c = c.replace(
    "const c4 = r.c4_reclaimed ? ('OK ' + (r.c4||'')) : '-';",
    "const c4 = r.c4_reclaimed ? ('\u2705 ' + (r.c4||'')) : '\u274c';"
)

c = c.replace(
    "const c1 = r.c1_hit ? ('OK ' + (r.c1||'')) : '-';",
    "const c1 = r.c1_hit ? ('\u2705 ' + (r.c1||'')) : '\u274c';"
)

c = c.replace(
    "const cw = r.call_wall_hit ? ('OK '+(r.call_wall||'')) : r.near_call_wall ? ('~ '+(r.call_wall||'')) : '-';",
    "const cw = r.call_wall_hit ? ('\u2705 '+(r.call_wall||'')) : r.near_call_wall ? ('~ '+(r.call_wall||'')) : '\u274c';"
)

with open('templates/index.html', 'w') as f:
    f.write(c)

# Verificar
found = all([
    "vol_trigger_lost" in c,
    "\u2705" in c,
    "\u274c" in c,
])
print("OK" if found else "ERRO - verificar")
