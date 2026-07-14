# RBC — Modo 8 · Equity Research v0.1-beta

Análise fundamentalista sell-side para mid caps industriais fora do radar:
screener → SEC EDGAR → scoring 4 pilares vs. pares → gate de red flags →
rating BUY/HOLD/SELL + preço-alvo → tese escrita pelo Claude.

---

## Arquivos

| Arquivo | Destino no repo |
|---|---|
| `rbc_research.py` | `~/RBC/rbc_research.py` |
| `research_routes.py` | `~/RBC/research_routes.py` |
| `research.html` | `~/RBC/templates/research.html` |

## Integração (3 passos)

**1. Dependências** — adicionar no `requirements.txt`:

```
requests>=2.31.0
yfinance>=0.2.40
psycopg2-binary>=2.9.9
```

**2. app.py** — duas linhas, depois do `app = Flask(...)`:

```python
from research_routes import research_bp
app.register_blueprint(research_bp)
```

**3. Aba no menu** — no `templates/index.html`, adicionar na barra de modos:

```html
<a href="/research">Modo 8 · Research</a>
```

## Teste local (SEMPRE antes do Railway)

```bash
cd ~/RBC
pip3 install requests yfinance

# Teste 1 — motor direto no terminal, 4 tickers (mais rápido):
python3 rbc_research.py AIT GGG DCI FELE

# Teste 2 — app completo:
python3 app.py
# → abrir http://localhost:5000/research
# → clicar "Rodar screener", depois "Atualizar fundamentos"
```

Se o Teste 1 imprimir a tabela de ratings sem traceback → APROVADO → commit:

```bash
git add rbc_research.py research_routes.py templates/research.html requirements.txt app.py
git commit -m "Modo 8: Equity Research — screener + EDGAR + rating 4 pilares"
git push
```

## Variáveis de ambiente (Railway)

| Var | Obrigatória | Função |
|---|---|---|
| `ANTHROPIC_API_KEY` | não (já existe) | tese sell-side escrita pelo Claude |
| `DATABASE_URL` | não (já existe) | grava histórico em `research_ratings` |
| `SEC_USER_AGENT` | recomendada | o SEC exige identificação, ex: `RBC Research seu@email.com` |

## Como usar (rotina)

- **1x por semana** (ou após earnings de nome da watchlist): abrir `/research` → Atualizar fundamentos → ler ratings e teses.
- **Cruzamento com Modo 5 Swing**: rating BUY = liberado viés comprador / venda de put; SELL = bloqueia viés comprador mesmo com setup técnico bom; HOLD = só estratégias neutras.
- **Screener**: revalidar 1x por mês — liquidez de opções e market cap mudam.

## Calibração (editar no topo do rbc_research.py)

- `UNIVERSE` — lista candidata de tickers (28 industriais mid cap de partida)
- `SCREEN` — mcap min/max, nº máx de analistas, OI mínimo, spread máximo
- `WEIGHTS` — pesos dos pilares (Qualidade 30 / Crescimento 25 / Balanço 20 / Valuation 25)
- `RATING_BUY` / `RATING_SELL` — cortes de 65 e 40

## Limitações conhecidas (v0.1)

- EDGAR: mapeamento de tags us-gaap tem fallbacks, mas 1-2 tickers podem vir
  com dados incompletos (o pipeline pula e avisa).
- Coleta completa do universo leva 1-2 min (rate limit de cortesia do SEC).
- Preço-alvo é por múltiplo relativo (EV/EBITDA justo vs. pares) — não é DCF.
- Ferramenta educacional. Não é recomendação de compra ou venda.
