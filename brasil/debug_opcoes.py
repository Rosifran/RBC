import os, requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

EMAIL = os.getenv("OPLAB_EMAIL")
SENHA = os.getenv("OPLAB_SENHA")

r = requests.post("https://api.oplab.com.br/v3/domain/users/authenticate",
    json={"email": EMAIL, "password": SENHA},
    headers={"Content-Type": "application/json"})
token = r.json().get("access-token")

r2 = requests.get("https://api.oplab.com.br/v3/market/options/PETR4",
    headers={"Access-Token": token})

opcoes = r2.json()
hoje = datetime.now().date()
data_alvo = hoje + timedelta(days=14)

print(f"Buscando opções próximas de {data_alvo}")
print()

for op in opcoes:
    venc = str(op.get('due_date',''))[:10]
    if '2026-06-05' in venc:
        print(f"{op.get('symbol')} | due_date: {venc} | strike: {op.get('strike')} | close: {op.get('close')}")
