#!/usr/bin/env python3
"""Script temporário para aplicar correções no /chat_ia do bot."""

import re

BOT_FILE = r"delivery_system\bot.py"

with open(BOT_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Corrigir _format_report (HTML limpo)
old_format_report = r'''    def _format_report\(title: str, k: dict\) -> str:
        eb_items = \[\]
        for t, v in sorted\(k\.get\("expense_breakdown", \{\}\)\.items\(\)\):
            eb_items\.append\(f"_\{t\}_: R\$ \{v:,\.2f\}"\)
        eb = " · "\.join\(eb_items\) or "-"
        return \(
            f"\*\{title\}\*\\n"
            f"📅 \*Período:\* `\{k\['period'\]\['start'\]\}` a `\{k\['period'\]\['end'\]\}`\\n"
            f"💵 \*Receita:\* R\$ \{k\['income_total'\]:,\.2f\}   ·   🧾 \*Despesas:\* R\$ \{k\['expense_total'\]:,\.2f\}\\n"
            f"💚 \*Lucro:\* R\$ \{k\['profit'\]:,\.2f\}   ·   🚘 \*KM:\* \{k\['km_total'\]:,\.0f\}\\n"
            f"🧩 \*Rotas:\* concl\\\\. \{k\['routes_completed'\]\} · final\\\\. \{k\['routes_finalized'\]\}\\n"
            f"📦 \*Entregues:\* \{k\['delivered'\]\} · ❌ \*Falhas:\* \{k\['failed'\]\} · ✅ \*Sucesso:\* \{k\['success_rate'\]:\.1f\}%\\n"
            f"📈 \*Médias por rota:\* Receita R\$ \{k\['avg_income_per_route'\]:,\.2f\} · Despesa R\$ \{k\['avg_expense_per_route'\]:,\.2f\}\\n"
            f"🏷️ \*Despesas por tipo:\* \{eb\}"
        \)'''

new_format_report = '''    def _format_report(title: str, k: dict) -> str:
        eb_items = []
        for t, v in sorted(k.get("expense_breakdown", {}).items()):
            eb_items.append(f"<i>{html.escape(t)}</i>: R$ {v:,.2f}")
        eb = " · ".join(eb_items) or "-"
        return (
            f"<b>{html.escape(title)}</b>\\n\\n"
            f"📅 <b>Período:</b> {html.escape(k['period']['start'])} a {html.escape(k['period']['end'])}\\n\\n"
            f"💵 <b>Receita:</b> R$ {k['income_total']:,.2f}\\n"
            f"🧾 <b>Despesas:</b> R$ {k['expense_total']:,.2f}\\n"
            f"💚 <b>Lucro:</b> R$ {k['profit']:,.2f}\\n"
            f"🚘 <b>KM Total:</b> {k['km_total']:,.0f} km\\n\\n"
            f"🧩 <b>Rotas:</b> {k['routes_completed']} concluídas · {k['routes_finalized']} finalizadas\\n"
            f"📦 <b>Entregas:</b> {k['delivered']} entregues · {k['failed']} falhas\\n"
            f"✅ <b>Taxa de Sucesso:</b> {k['success_rate']:.1f}%\\n\\n"
            f"📈 <b>Médias por rota:</b>\\n"
            f"   • Receita: R$ {k['avg_income_per_route']:,.2f}\\n"
            f"   • Despesa: R$ {k['avg_expense_per_route']:,.2f}\\n\\n"
            f"🏷️ <b>Despesas por tipo:</b> {eb}"
        )'''

content = re.sub(old_format_report, new_format_report, content, flags=re.DOTALL)

# 2. Trocar MarkdownV2 por HTML nos send_message
content = content.replace("parse_mode='MarkdownV2')", "parse_mode='HTML')")

# 3. Mudar prompt system e user
old_sys = '''        sys = (
            "Você é um CFO (diretor financeiro) experiente de uma empresa de entregas. "
            "Sua missão é dar análises estratégicas completas e acionáveis com base nos dados fornecidos. "
            "Foque em: (1) Tendências e padrões (crescimento/queda receita, despesas, lucro), "
            "(2) Comparações entre períodos (semanal, mensal), "
            "(3) Riscos operacionais e financeiros, "
            "(4) Oportunidades de otimização (rotas, salários, custos), "
            "(5) Projeções e recomendações para os próximos períodos. "
            "Responda em pt-BR, de forma direta mas profunda, em 8-15 bullets curtos (máx. 25 palavras cada). "
            "Use negrito em **termos-chave** e itálico em *valores importantes*. "
            "Mostre domínio dos números e não hesite em apontar alertas vermelhos ou bandeiras verdes. "
            "Evite generalizações sem dado. Seja assertivo e confiável."
        )
        usr = (
            f"Pergunta/Pedido: {question}\\n\\n"
            f"Dados detalhados (JSON):\\n{json.dumps(context_blob, indent=2, ensure_ascii=False)}"
        )'''

new_sys = '''        sys = (
            "Você é um consultor financeiro experiente e amigável de uma empresa de entregas. "
            "Seu trabalho é EXPLICAR os números, dar CONTEXTO e sugerir AÇÕES PRÁTICAS — não só listar dados. "
            "\\n\\nComo responder:\\n"
            "1. RESUMO (1-2 frases): O que os números dizem sobre a saúde do negócio agora?\\n"
            "2. ANÁLISE (3-5 pontos): Por que isso está acontecendo? Tendências, comparações, causas.\\n"
            "3. ALERTAS (1-3 pontos): Riscos ou problemas que merecem atenção imediata.\\n"
            "4. RECOMENDAÇÕES (3-5 ações concretas): O que fazer agora? Seja específico e prático.\\n"
            "\\nTom: Consultivo, direto, amigável. Fale como se estivesse conversando com o dono da empresa tomando café.\\n"
            "Use negrito em **termos importantes** e dê exemplos reais quando possível.\\n"
            "Evite jargões complexos. Seja humano, não robotizado.\\n"
            "Tamanho: 10-18 linhas no total (não seja curto demais)."
        )
        usr = (
            f"Contexto: Empresa de entregas na Rocinha (RJ), modelo micro-hub com entregadores locais a pé.\\n\\n"
            f"Pergunta do dono: {question}\\n\\n"
            f"Dados financeiros e operacionais (JSON completo):\\n"
            f"{json.dumps(context_blob, indent=2, ensure_ascii=False)}\\n\\n"
            f"Instruções extras:\\n"
            f"- Se for sobre contratar mais gente, considere: custo R$ 100-150/dia por entregador, capacidade ~30 pacotes/dia cada.\\n"
            f"- Se for sobre combustível, considere: despesa principal do negócio, buscar otimização de rotas.\\n"
            f"- Se for sobre escala, foque em: eficiência operacional, taxa de sucesso, relacionamento com cliente (Shopee).\\n"
            f"- Sempre que possível, dê números concretos (ex: 'economizar R$ X', 'aumentar Y%', 'contratar Z pessoas')."
        )'''

content = content.replace(old_sys, new_sys)

# 4. Trocar temperature e max_tokens + fallback com HTML
content = content.replace('temperature=0.2,\n                max_tokens=1200,', 
                          'temperature=0.3,\n                max_tokens=1500,')

content = content.replace(
    '''        except Exception:
            raw = (
                "Não consegui acessar a IA agora. Segue contexto numérico:\\n\\n" +''',
    '''        except Exception as e:
            raw = (
                f"⚠️ Não consegui acessar a IA agora ({e}). Segue contexto numérico:\\n\\n" +'''
)

# 5. Trocar processamento final (HTML ao invés de Markdown)
old_final_block = '''        # Limpa e formata a resposta em Markdown limpo
        def clean_md(text: str) -> str:
            # Remove espaços excessivos, normaliza quebras
            t = text.replace('\\r', '').strip()
            # Substitui bullets de hífen por bullets reais
            lines = []
            for line in t.split('\\n'):
                s = line.strip()
                if s.startswith('- ') or s.startswith('* '):
                    lines.append('• ' + s[2:].strip())
                elif s:
                    lines.append(s)
            return '\\n'.join(lines)

        answer = clean_md(raw)
        # Monta mensagem final com cabeçalho e corpo
        header = f"🧮 *Parecer Financeiro (CFO)*\\n💬 _{question}_\\n"
        final_msg = header + "\\n" + answer
        try:
            await context.bot.send_message(chat_id=target_chat_id, text=final_msg, parse_mode='Markdown')
        except Exception:
            # Fallback sem formatação se Markdown falhar
            await update.message.reply_text(final_msg.replace('*', '').replace('_', ''))'''

new_final_block = '''        # Formata resposta em HTML limpo e organizado
        def format_advice(text: str) -> str:
            lines = []
            for line in text.split('\\n'):
                s = line.strip()
                if not s:
                    continue
                # Converte **bold** para <b>
                s = re.sub(r'\\*\\*([^*]+)\\*\\*', r'<b>\\1</b>', s)
                # Converte *italic* para <i>
                s = re.sub(r'(?<!\\*)\\*([^*]+)\\*(?!\\*)', r'<i>\\1</i>', s)
                # Converte bullets
                if s.startswith('- ') or s.startswith('• '):
                    s = '  • ' + s[2:].strip()
                elif s.startswith('* '):
                    s = '  • ' + s[2:].strip()
                # Detecta seções (RESUMO, ANÁLISE, etc.) e destaca
                if any(kw in s.upper() for kw in ['RESUMO', 'ANÁLISE', 'ALERTAS', 'RECOMENDAÇÕES', 'RECOMENDACAO']):
                    s = f"\\n<b>{s}</b>"
                lines.append(html.escape(s) if '<b>' not in s and '<i>' not in s else s)
            return '\\n'.join(lines)

        advice = format_advice(raw)
        header = f"🧮 <b>Parecer Financeiro (CFO)</b>\\n💬 <i>{html.escape(question)}</i>\\n"
        final_msg = header + "\\n" + advice
        
        try:
            await context.bot.send_message(chat_id=target_chat_id, text=final_msg, parse_mode='HTML')
        except Exception as send_err:
            # Fallback: remove toda formatação e envia texto puro
            plain = re.sub(r'<[^>]+>', '', final_msg)
            await update.message.reply_text(plain)'''

content = content.replace(old_final_block, new_final_block)

# Salvar
with open(BOT_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Arquivo bot.py atualizado com sucesso!")
print("🔍 Verificando erros...")

import subprocess
result = subprocess.run(['python', '-m', 'py_compile', BOT_FILE], capture_output=True, text=True)
if result.returncode == 0:
    print("✅ Nenhum erro de sintaxe detectado!")
else:
    print(f"❌ Erro de sintaxe:\n{result.stderr}")
