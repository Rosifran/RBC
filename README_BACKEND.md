# RBC Backend

Arquivos para colocar na raiz do repositório `RBC`.

## Rodar local

```bash
pip install -r requirements.txt
python app.py
```

Abra:

```text
http://localhost:5000/health
```

## Teste Modo 1

```bash
curl -X POST http://localhost:5000/api/modo1 \
  -H "Content-Type: application/json" \
  -d '{"raw_string":"$SPY, SPY, 745, 730, 740, 738, 735, 732, 728, 740, 745, 735, 730, 0.006, 0.015, 738"}'
```

## Deploy Railway

O Railway precisa encontrar:

```text
app.py
rbc_0dte_scanner.py
requirements.txt
Procfile
```

Start command:

```text
gunicorn app:app
```
