# 🤖 Configuração da API Google Gemini

## Visão Geral

O sistema agora possui **relatórios financeiros inteligentes** gerados por IA usando o Google Gemini. Este guia mostra como configurar.

---

## 🎯 Obter Chave da API (GRATUITA)

1. **Acesse o Google AI Studio:**
   - URL: https://aistudio.google.com/app/apikey

2. **Faça login com sua conta Google**

3. **Clique em "Get API Key" ou "Create API Key"**
   - Selecione ou crie um projeto
   - A chave será gerada instantaneamente

4. **Copie a chave** (formato: `AIza...`)

---

## ⚙️ Configurar no Sistema

### Opção 1: Variável de Ambiente (Produção - Render)

No painel do Render:

1. Vá em **Environment** → **Environment Variables**
2. Adicione nova variável:
   - **Key:** `GEMINI_API_KEY`
   - **Value:** `sua_chave_aqui`
3. Clique em **Save Changes**
4. O serviço será reiniciado automaticamente

### Opção 2: Arquivo .env (Desenvolvimento Local)

Edite o arquivo `delivery_system/.env`:

```properties
# Google Gemini API Key (get from https://aistudio.google.com/app/apikey)
GEMINI_API_KEY=AIzaSy...
```

---

## 📊 Como Usar

### Comando no Telegram

```
/relatorio
```

**Apenas gerentes podem usar este comando.**

### O que a IA analisa:

✅ **Entregas do Mês:**
- Total de pacotes
- Taxa de sucesso
- Pacotes com falha

✅ **Operações:**
- Rotas criadas
- Motoristas ativos
- Média de pacotes por rota

✅ **Registros Financeiros:**
- Receitas registradas
- Despesas registradas
- Quilometragem

### Resultado:

A IA Gemini gera um relatório completo com:

1. 📈 **Resumo Executivo**
2. 🚚 **Desempenho Operacional**
3. 💰 **Análise Financeira**
4. 💡 **Recomendações Acionáveis**

---

## 🔒 Segurança

- ✅ Chave armazenada em variável de ambiente (não no código)
- ✅ Relatórios salvos no banco de dados
- ✅ Apenas gerentes têm acesso
- ✅ Dados nunca expostos publicamente

---

## 💰 Custos

O Google Gemini oferece:

- **Tier Gratuito Generoso:**
  - 60 requisições por minuto
  - 1500 requisições por dia
  - Grátis para sempre

- **Suficiente para:**
  - Vários relatórios diários
  - Uso normal do sistema
  - Testes e desenvolvimento

---

## 🐛 Troubleshooting

### Erro: "IA Não Configurada"

**Causa:** Chave da API não definida ou inválida.

**Solução:**
1. Verifique se `GEMINI_API_KEY` está no `.env` ou Render
2. Confirme que a chave não é `your_api_key_here`
3. Reinicie o bot após adicionar a chave

### Erro: "Erro ao gerar relatório"

**Possíveis causas:**
1. Chave da API inválida ou expirada
2. Limite de requisições atingido (raro)
3. Problema de conexão com a API do Google

**Solução:**
1. Gere uma nova chave no Google AI Studio
2. Aguarde alguns minutos e tente novamente
3. Verifique logs do sistema

---

## 📝 Exemplo de Uso

### Gerente envia:
```
/relatorio
```

### Bot responde:
```
🤖 Gerando Relatório...
⏳ Coletando dados financeiros e de entregas...
🧠 IA analisando dados...

📊 Relatório Financeiro - Outubro/2025

[Análise detalhada gerada pela IA...]

✅ Relatório salvo!
🤖 Gerado por IA Gemini
📅 15/10/2025 14:30
```

---

## 🚀 Recursos Futuros

Planejado para próximas versões:

- 📊 Relatórios semanais automatizados
- 📈 Gráficos e visualizações
- 🎯 Previsões de demanda
- 💡 Sugestões de otimização de rotas
- 📧 Envio automático por e-mail

---

## 📞 Suporte

Para problemas com a configuração:

1. Verifique este guia completamente
2. Teste com `/relatorio` no Telegram
3. Consulte os logs do sistema
4. Contate o desenvolvedor se necessário

---

**Última atualização:** Outubro 2025
**Versão do Gemini:** 1.5 Pro (gemini-pro)
