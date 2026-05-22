with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'r') as f:
    content = f.read()

content = content.replace(
    "alvo_venda = spot * 0.99",
    "alvo_venda = spot * 0.98"
)

with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'w') as f:
    f.write(content)
print("✅ Corrigido!")
