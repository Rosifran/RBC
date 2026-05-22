with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'r') as f:
    content = f.read()

# Calls B3: letras A-L na posição 4 do símbolo
# Puts  B3: letras M-X na posição 4 do símbolo
content = content.replace(
    "calls = [op for op in opcoes if 'E' in op.get('symbol', '')[4:5]]",
    "calls = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'ABCDEFGHIJKL']"
)
content = content.replace(
    "puts = [op for op in opcoes if 'Q' in op.get('symbol', '')[4:5]]",
    "puts = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'MNOPQRSTUVWX']"
)
content = content.replace(
    "letra = 'E' if tipo == 'call' else 'Q'\n    filtradas = [op for op in opcoes if letra in op.get('symbol', '')[4:5]]",
    "if tipo == 'call':\n        filtradas = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'ABCDEFGHIJKL']\n    else:\n        filtradas = [op for op in opcoes if op.get('symbol', '')[4:5].upper() in 'MNOPQRSTUVWX']"
)

with open('/Users/rosi/RBC/brasil/rbc_br_scanner.py', 'w') as f:
    f.write(content)
print("✅ Corrigido!")
