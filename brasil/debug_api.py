import os, json, requests
from dotenv import load_dotenv
load_dotenv()

EMAIL = os.getenv("OPLAB_EMAIL")
SENHA = os.getenv("OPLAB_SENHA")

r = requests.post("https://api.oplab.com.br/v3/domain/users/authenticate",
    json={"email": EMAIL, "password": SENHA},
    headers={"Content-Type": "application/json"})
token = r.json().get("access-token")

r2 = requests.get("https://api.oplab.com.br/v3/market/stocks/PETR4",
    headers={"Access-Token": token})
print(json.dumps(r2.json(), indent=2))
