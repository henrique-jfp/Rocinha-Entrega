# Checklist de Variáveis Railway

Verifique se TODAS essas variáveis estão configuradas:

## Obrigatórias:
- [ ] BOT_TOKEN
- [ ] BOT_USERNAME (ex: @seu_bot)
- [ ] DATABASE_URL (PostgreSQL Supabase)
- [ ] BASE_URL (gerada após primeiro deploy)
- [ ] PORT=8000

## Opcionais:
- [ ] GEMINI_API_KEY (para /relatorio funcionar)

## Como verificar:
1. Railway Dashboard > Seu Projeto > Variables
2. Conferir se todas estão preenchidas
3. BASE_URL deve ter https:// no início

## Logs úteis:
- Build logs: Mostra se o Docker foi construído
- Deploy logs: Mostra se o app iniciou
- Procure por: "✅ Bot iniciado com webhook"
