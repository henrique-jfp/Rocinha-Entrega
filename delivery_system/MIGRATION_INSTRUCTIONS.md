# 🔧 Instruções de Migration - Automação Financeira

## 🚨 **PROBLEMA IDENTIFICADO**

O bot está falhando porque a coluna `revenue` (e outras colunas de automação financeira) **não existe no banco de dados PostgreSQL do Railway**.

**Erro nos logs:**
```
[ERROR] (psycopg2.errors.UndefinedColumn) column route.revenue does not exist
```

---

## ✅ **SOLUÇÃO: Aplicar Migration**

### **Opção 1: Executar Script Python (RECOMENDADO)**

Execute o script de migration que aplica automaticamente todas as alterações:

```bash
python delivery_system/apply_route_automation.py
```

**O que o script faz:**
- ✅ Adiciona 8 colunas na tabela `route`: `revenue`, `driver_salary`, `status`, `completed_at`, `finalized_at`, `extra_expenses`, `extra_income`, `calculated_km`
- ✅ Adiciona 2 colunas na tabela `expense`: `route_id`, `confirmed`
- ✅ Atualiza rotas existentes (status = 'in_progress' se já tiverem motorista)
- ✅ Cria índices para melhor performance
- ✅ Verifica se colunas já existem (não duplica)

---

### **Opção 2: SQL Manual (Railway Console)**

Se não conseguir executar o script Python, aplique o SQL manualmente no **Railway Database**:

1. Abra o projeto no Railway
2. Vá em **Database** → **Query**
3. Cole e execute o SQL abaixo:

```sql
-- Migration: Adiciona campos para automação financeira de rotas
-- Data: 18/10/2025

-- Adiciona novos campos na tabela Route
ALTER TABLE route ADD COLUMN IF NOT EXISTS revenue REAL DEFAULT 260.0 NOT NULL;
ALTER TABLE route ADD COLUMN IF NOT EXISTS driver_salary REAL;
ALTER TABLE route ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending' NOT NULL;
ALTER TABLE route ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
ALTER TABLE route ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMP;
ALTER TABLE route ADD COLUMN IF NOT EXISTS extra_expenses REAL DEFAULT 0.0 NOT NULL;
ALTER TABLE route ADD COLUMN IF NOT EXISTS extra_income REAL DEFAULT 0.0 NOT NULL;
ALTER TABLE route ADD COLUMN IF NOT EXISTS calculated_km REAL;

-- Adiciona novos campos na tabela Expense
ALTER TABLE expense ADD COLUMN IF NOT EXISTS route_id INTEGER REFERENCES route(id) ON DELETE SET NULL;
ALTER TABLE expense ADD COLUMN IF NOT EXISTS confirmed INTEGER DEFAULT 1 NOT NULL;

-- Atualiza rotas existentes
UPDATE route SET status = 'in_progress' WHERE assigned_to_id IS NOT NULL AND status = 'pending';

-- Cria índices para melhor performance
CREATE INDEX IF NOT EXISTS idx_route_status ON route(status);
CREATE INDEX IF NOT EXISTS idx_expense_route_id ON expense(route_id);
CREATE INDEX IF NOT EXISTS idx_expense_confirmed ON expense(confirmed);
```

---

### **Opção 3: Adicionar ao Dockerfile (Automático no Deploy)**

Adicione ao `Dockerfile.unified` para executar automaticamente no deploy:

```dockerfile
# Antes do CMD
RUN python apply_route_automation.py || echo "Migration já aplicada"

CMD python -u bot.py
```

⚠️ **Cuidado:** Isso executará TODA VEZ que o container subir. Prefira Opção 1 ou 2.

---

## 🔍 **Verificação Após Migration**

Execute no Railway Database Query:

```sql
-- Verificar se colunas foram criadas
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns 
WHERE table_name = 'route'
ORDER BY ordinal_position;
```

**Resultado esperado:** Deve mostrar as 8 novas colunas:
- `revenue` (REAL, DEFAULT 260.0, NOT NULL)
- `driver_salary` (REAL, NULL)
- `status` (TEXT, DEFAULT 'pending', NOT NULL)
- `completed_at` (TIMESTAMP, NULL)
- `finalized_at` (TIMESTAMP, NULL)
- `extra_expenses` (REAL, DEFAULT 0.0, NOT NULL)
- `extra_income` (REAL, DEFAULT 0.0, NOT NULL)
- `calculated_km` (REAL, NULL)

---

## 🎯 **Após Aplicar Migration**

1. ✅ O Railway irá **reiniciar automaticamente** o bot
2. ✅ Teste os comandos:
   - `/importar` - Deve funcionar normalmente
   - `/enviarrota` - Deve calcular salário automaticamente
   - `/rastrear` - Deve mostrar status financeiro
   - `/relatorio` - Deve gerar análise financeira completa

3. ✅ Monitore os logs:
   ```bash
   # No Railway, vá em Deployments → View Logs
   # NÃO deve mais aparecer: "column route.revenue does not exist"
   ```

---

## 📚 **Arquivo SQL da Migration**

O SQL completo está em:
```
delivery_system/migrations/add_route_automation_fields.sql
```

---

## 🐛 **Troubleshooting**

### "Permission denied" ao executar script Python
```bash
# Certifique-se de ter DATABASE_URL configurada
echo $DATABASE_URL

# Se vazio, configure no .env:
DATABASE_URL=postgresql://user:pass@host:port/database
```

### "Column already exists"
✅ Normal! Significa que a coluna já foi adicionada. Ignore e continue.

### "Table does not exist"
❌ Problema maior. Execute primeiro:
```bash
python delivery_system/database.py
```

---

## 💡 **Dicas para Logs de Erro**

Quando encontrar erros no Railway, sempre copie:

1. **Logs de Deploy (Build):**
   - Deployments → Latest → Build Logs
   - Mostra erros de instalação de dependências

2. **Logs de Runtime (Deploy):**
   - Deployments → Latest → Deploy Logs
   - Mostra erros de execução do bot

3. **Logs de Database:**
   - Database → Logs
   - Mostra queries SQL com erro

4. **Query direta no banco:**
   ```sql
   -- Ver estrutura de tabelas
   \d route
   \d expense
   
   -- Ver todas as tabelas
   SELECT tablename FROM pg_tables WHERE schemaname = 'public';
   ```

---

## ✅ **Checklist de Resolução**

- [ ] Migration aplicada (Opção 1 ou 2)
- [ ] Colunas verificadas no banco
- [ ] Bot reiniciado no Railway
- [ ] Logs sem erros "column does not exist"
- [ ] Comandos /importar, /enviarrota testados
- [ ] /relatorio funcionando com análise financeira

---

**Data:** 18/10/2025  
**Fase:** 4.1 - Automação Financeira  
**Versão:** 1.0.0
