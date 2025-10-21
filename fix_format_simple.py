#!/usr/bin/env python3
"""Script simples para corrigir a função format_advice"""

# Lê o arquivo
with open('delivery_system/bot.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Encontra a linha com "def clean_md"
start_idx = None
for i, line in enumerate(lines):
    if 'def clean_md(text: str) -> str:' in line:
        start_idx = i - 1  # inclui o comentário acima
        break

if start_idx is None:
    print("❌ Função clean_md não encontrada")
    exit(1)

# Encontra o final (após reply_text)
end_idx = None
for i in range(start_idx, len(lines)):
    if "await update.message.reply_text(final_msg.replace('*', '').replace('_', ''))" in lines[i]:
        end_idx = i + 1
        break

if end_idx is None:
    print("❌ Final da seção não encontrado")
    exit(1)

print(f"Substituindo linhas {start_idx+1} a {end_idx}")

# Novo código
new_lines = [
    "        # Formata a resposta para HTML\n",
    "        def format_advice(text: str) -> str:\n",
    "            # Remove espaços excessivos, normaliza quebras\n",
    "            t = text.replace('\\r', '').strip()\n",
    "            # Converte Markdown para HTML\n",
    "            t = re.sub(r'\\*\\*([^*]+)\\*\\*', r'<b>\\1</b>', t)  # negrito\n",
    "            t = re.sub(r'\\*([^*]+)\\*', r'<i>\\1</i>', t)  # itálico\n",
    "            # Detecta seções com emoji e deixa em negrito\n",
    "            t = re.sub(r'^(📌 RESUMO:|🔍 ANÁLISE:|⚠️ ALERTAS:|✅ RECOMENDAÇÕES:)', r'<b>\\1</b>', t, flags=re.MULTILINE)\n",
    "            # Normaliza bullets\n",
    "            lines = []\n",
    "            for line in t.split('\\n'):\n",
    "                s = line.strip()\n",
    "                if s.startswith('- ') or s.startswith('* '):\n",
    "                    lines.append('  • ' + s[2:].strip())\n",
    "                elif s:\n",
    "                    lines.append(s)\n",
    "            return '\\n'.join(lines)\n",
    "\n",
    "        answer = format_advice(raw)\n",
    "        # Monta mensagem final com cabeçalho e corpo\n",
    "        header = f\"<b>🧮 Parecer Financeiro</b>\\n<i>{html.escape(question)}</i>\\n\"\n",
    "        final_msg = header + \"\\n\" + answer\n",
    "        try:\n",
    "            await context.bot.send_message(chat_id=target_chat_id, text=final_msg, parse_mode='HTML')\n",
    "        except Exception as e:\n",
    "            # Fallback sem formatação se HTML falhar\n",
    "            plain = final_msg.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '')\n",
    "            await update.message.reply_text(plain)\n",
]

# Substitui
new_content = lines[:start_idx] + new_lines + lines[end_idx:]

# Salva
with open('delivery_system/bot.py', 'w', encoding='utf-8') as f:
    f.writelines(new_content)

print("✅ Substituição concluída!")

# Verifica sintaxe
import py_compile
try:
    py_compile.compile('delivery_system/bot.py', doraise=True)
    print("✅ Sintaxe OK!")
except py_compile.PyCompileError as e:
    print(f"❌ Erro de sintaxe:\n{e}")
