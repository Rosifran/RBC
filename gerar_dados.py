"""
RBC — Gerador de dados_hoje.txt
================================
Cole a string do SpotGamma aqui e salva em dados_hoje.txt
para o scanner ler automaticamente.

Uso:
    python gerar_dados.py
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("\n" + "═"*60)
print("  RBC | Gerador de dados_hoje.txt")
print("═"*60)
print("""
  Cole a string do SpotGamma que eu preparo para você.
  Pressiona Enter duas vezes quando terminar.
""")

lines = []
while True:
    line = input()
    if line == '' and lines:
        break
    lines.append(line)

raw = ' '.join(lines).strip()

if not raw:
    print("  Nenhum dado inserido.")
else:
    path = os.path.join(BASE_DIR, 'dados_hoje.txt')
    with open(path, 'w') as f:
        f.write(raw)
    print(f"\n  ✅ dados_hoje.txt salvo em {path}")
    print(f"  O scanner vai carregar automaticamente na próxima execução.")
    print(f"\n  Conteúdo salvo ({len(raw)} caracteres):")
    print(f"  {raw[:80]}...")
