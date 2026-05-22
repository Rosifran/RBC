import os
import requests
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("OPLAB_EMAIL")
SENHA = os.getenv("OPLAB_SENHA")
BASE_URL = "https://api.oplab.com.br/v3"

def autenticar():
    r = requests.post(
        f"{BASE_URL}/domain/users/authenticate",
        json={"email": EMAIL, "password": SENHA},
        headers={"Content-Type": "application/json"}
    )
    return r.json().get("access-token")

def buscar_opcoes(token, ativo="PETR4"):
    headers = {"Access-Token": token}
    r = requests.get(f"{BASE_URL}/market/options/{ativo}", headers=headers)
    if r.status_code == 200:
        opcoes = r.json()
        print(f"\n📊 PETR4 — {len(opcoes)} contratos | Mostrando ATM venc 22/05\n")
        print(f"{'Símbolo':<14} {'Tipo':<5} {'Strike':>7} {'Venc':<12} {'Delta':>7} {'IV':>7} {'Prêmio':>8}")
        print("-" * 70)
        for op in opcoes:
            venc = op.get('due_date', '')
            if '2026-05-22' not in str(venc):
                continue
            simbolo = op.get('symbol', '')
            categoria = op.get('category', '')
            strike = op.get('strike', 0)
            delta = op.get('delta', '-')
            iv = op.get('implied_volatility', '-')
            premio = op.get('close', '-')
            tipo = 'CALL' if 'E' in simbolo[4] else 'PUT'
            print(f"{simbolo:<14} {tipo:<5} {strike:>7.2f} {str(venc):<12} {str(delta):>7} {str(iv):>7} {str(premio):>8}")
    else:
        print(f"❌ Erro: {r.status_code}")

if __name__ == "__main__":
    token = autenticar()
    buscar_opcoes(token, "PETR4")
