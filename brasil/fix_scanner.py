with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'r') as f:
    content = f.read()

# Fix 1: vencimento minimo 14 dias
content = content.replace(
    'dias_min=7, dias_max=28',
    'dias_min=14, dias_max=35'
)

# Fix 2: theta positivo no put spread vendido
content = content.replace(
    "round(g_venda['theta'] - g_compra['theta'], 4)",
    "round(abs(g_venda['theta']) - abs(g_compra['theta']), 4)"
)

with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'w') as f:
    f.write(content)
print("✅ Corrigido!")
