# Fix 1: journal.py - não sobrescrever com nulls
with open('journal.py', 'r') as f:
    c = f.read()

old1 = "    vals = {f: data.get(f) for f in fields}"
new1 = "    vals = {f: data.get(f) for f in fields if data.get(f) is not None}\n    if 'date' not in vals:\n        vals['date'] = date.today().isoformat()"

old2 = "    vals[\"weekday\"] = vals[\"weekday\"] or date.fromisoformat(str(vals[\"date\"])).strftime(\"%A\")"
new2 = "    vals[\"weekday\"] = vals.get(\"weekday\") or date.fromisoformat(str(vals[\"date\"])).strftime(\"%A\")"

if old1 in c:
    c = c.replace(old1, new1)
    print("OK filter nulls")
else:
    print("ERRO filter nulls")

if old2 in c:
    c = c.replace(old2, new2)
    print("OK weekday")
else:
    print("ERRO weekday")

with open('journal.py', 'w') as f:
    f.write(c)
print("journal.py salvo")
