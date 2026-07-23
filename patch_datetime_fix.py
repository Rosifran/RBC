"""
RBC — patch fix datetime import + fresh no tv_quote_get
Adiciona import datetime no topo do app.py.
Uso: python3 patch_datetime_fix.py ~/RBC/app.py
"""
import sys, shutil, ast
from datetime import datetime

OLD = '''import io
import json
import os'''

NEW = '''import io
import json
import os
from datetime import datetime, timezone'''

if len(sys.argv) < 2:
    print("Uso: python3 patch_datetime_fix.py ~/RBC/app.py")
    sys.exit(1)

path = sys.argv[1]
content = open(path).read()

if OLD not in content:
    print("ERRO — âncora não encontrada.")
    sys.exit(1)

if 'from datetime import datetime' in content:
    print("AVISO — datetime já importado. Nada alterado.")
    sys.exit(0)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(path, path.replace(".py", f"_backup_{ts}.py"))
print(f"Backup criado")

content = content.replace(OLD, NEW, 1)
ast.parse(content)
open(path, 'w').write(content)
print("✅ import datetime adicionado")
print("✅ fresh e ts_str vão funcionar corretamente")
