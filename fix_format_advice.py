#!/usr/bin/env python3
"""Script para corrigir a função format_advice no bot.py"""

import re

# Lê o arquivo
with open('delivery_system/bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern para encontrar a seção a ser substituída
old_pattern = re.compile(
    r'# Limpa e formata a resposta em Markdown limpo\s+'
    r'def clean_md\(text: str\) -> str:.*?'
    r'await update\.message\.reply_text\(final_msg\.replace\(\'\*\', \'\'\)\.replace\(\'_\', \'\'\)\)',
    re.DOTALL
)

new_code = """# Formata a resposta para HTML
        def format_advice(text: str) -> str:
            # Remove espaços excessivos, normaliza quebras
            t = text.replace('\\r', '').strip()
            # Converte Markdown para HTML
            t = re.sub(r'\\*\\*([^*]+)\\*\\*', r'<b>\\1</b>', t)  # negrito
            t = re.sub(r'\\*([^*]+)\\*', r'<i>\\1</i>', t)  # itálico
            # Detecta seções com emoji e deixa em negrito
            t = re.sub(r'^(📌 RESUMO:|🔍 ANÁLISE:|⚠️ ALERTAS:|✅ RECOMENDAÇÕES:)', r'<b>\\1</b>', t, flags=re.MULTILINE)
            # Normaliza bullets
            lines = []
            for line in t.split('\\n'):
                s = line.strip()
                if s.startswith('- ') or s.startswith('* '):
                    lines.append('  • ' + s[2:].strip())
                elif s:
                    lines.append(s)
            return '\\n'.join(lines)

        answer = format_advice(raw)
        # Monta mensagem final com cabeçalho e corpo
        header = f"<b>🧮 Parecer Financeiro</b>\\n<i>{html.escape(question)}</i>\\n"
        final_msg = header + "\\n" + answer
        try:
            await context.bot.send_message(chat_id=target_chat_id, text=final_msg, parse_mode='HTML')
        except Exception as e:
            # Fallback sem formatação se HTML falhar
            plain = final_msg.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '')
            await update.message.reply_text(plain)"""

# Substitui
new_content = old_pattern.sub(new_code, content)

if new_content == content:
    print("❌ Nenhuma substituição foi feita - padrão não encontrado")
else:
    # Salva
    with open('delivery_system/bot.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("✅ Substituição concluída com sucesso!")

    # Verifica sintaxe
    import py_compile
    try:
        py_compile.compile('delivery_system/bot.py', doraise=True)
        print("✅ Sintaxe OK!")
    except py_compile.PyCompileError as e:
        print(f"❌ Erro de sintaxe: {e}")
