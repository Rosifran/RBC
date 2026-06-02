with open('journal.py', 'r') as f:
    c = f.read()

# CREATE_TABLE
old1 = "    vol_trigger_lost    BOOLEAN\n);"
new1 = "    vol_trigger_lost      BOOLEAN,\n    vol_trigger_lost_time VARCHAR(10)\n);"
if old1 in c:
    c = c.replace(old1, new1); print("OK CREATE_TABLE")
else: print("ERRO CREATE_TABLE")

# ALTER TABLE
old2 = '                ("vol_trigger_lost",  "BOOLEAN"),'
new2 = '                ("vol_trigger_lost",       "BOOLEAN"),\n                ("vol_trigger_lost_time", "VARCHAR(10)"),'
if old2 in c:
    c = c.replace(old2, new2); print("OK ALTER TABLE")
else: print("ERRO ALTER TABLE")

# fields
old3 = '"max_spy","min_spy","trade_path","trade_quality","vol_trigger_lost"'
new3 = '"max_spy","min_spy","trade_path","trade_quality","vol_trigger_lost","vol_trigger_lost_time"'
if old3 in c:
    c = c.replace(old3, new3); print("OK fields")
else: print("ERRO fields")

with open('journal.py', 'w') as f:
    f.write(c)
print("Salvo")
