import os, requests, json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

EMAIL    = os.getenv("OPLAB_EMAIL")
SENHA    = os.getenv("OPLAB_PASSWORD") or os.getenv("OPLAB_SENHA")
BASE_URL = "https://api.oplab.com.br/v3"

print(f"EMAIL: {EMAIL}")
print(f"SENHA carregada: {bool(SENHA)}")

r = requests.post(f"{BASE_URL}/domain/users/authenticate",
    json={"email": EMAIL, "password": SENHA},
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    timeout=20)

print(f"AUTH STATUS: {r.status_code}")
print(f"AUTH RESPONSE: {r.text[:300]}")

if r.status_code != 200:
    exit(1)

data = r.json()
token = (
    data.get("access-token")
    or data.get("access_token")
    or data.get("token")
)

if not token:
    print("Token nao encontrado:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    exit(1)

print(f"Token OK: {token[:20]}...")

headers_at = {"Access-Token": token, "Accept": "application/json"}
headers_br = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

endpoints = [
    "/market/stocks/PETR4",
    "/market/options/PETR4",
    "/market/volatility/PETR4",
    "/domain/users/me",
]

for ep in endpoints:
    print(f"\n{'='*40}")
    print(f"GET {ep}")
    r2 = requests.get(f"{BASE_URL}{ep}", headers=headers_at, timeout=20)
    if r2.status_code in [401, 403]:
        print("Tentando Bearer...")
        r2 = requests.get(f"{BASE_URL}{ep}", headers=headers_br, timeout=20)
    print(f"STATUS: {r2.status_code}")
    if r2.status_code == 200:
        d = r2.json()
        if isinstance(d, list):
            print(f"Lista com {len(d)} itens. Keys: {list(d[0].keys()) if d else '[]'}")
        else:
            print(f"Keys: {list(d.keys())}")
    else:
        print(r2.text[:300])
