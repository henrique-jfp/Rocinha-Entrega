# 🔄 Instruções para Aplicar Migração CASCADE DELETE

## ⚠️ IMPORTANTE: Aplique esta migração no Railway

Esta migração altera o comportamento de exclusão de rotas para **CASCADE DELETE**.

## 📋 O que a migração faz:

### Antes (SET NULL):
```
Excluir Rota #15
├─ Pacotes: DELETADOS ✅
├─ Provas: DELETADAS ✅
├─ Salários: DELETADOS ✅
├─ Receitas: MANTIDAS (route_id = NULL) ⚠️
└─ Despesas: MANTIDAS (route_id = NULL) ⚠️
```

### Depois (CASCADE):
```
Excluir Rota #15
├─ Pacotes: DELETADOS ✅
├─ Provas: DELETADAS ✅
├─ Salários: DELETADOS ✅
├─ Receitas: DELETADAS ✅
└─ Despesas: DELETADAS ✅
```

**Resultado**: Ao excluir uma rota, é como se ela nunca tivesse existido!

---

## 🚀 Como Aplicar no Railway

### Opção 1: Via SSH no Railway (RECOMENDADO)

1. **Conecte ao container**:
   ```bash
   railway connect
   ```

2. **Execute a migração**:
   ```bash
   cd /app
   python delivery_system/apply_cascade_migration.py
   ```

3. **Verifique o resultado**:
   - Deve mostrar: "✅ Migração aplicada com sucesso!"
   - Backup será criado automaticamente

---

### Opção 2: Aplicar manualmente via SQL

1. **Acesse o banco SQLite no Railway**

2. **Execute o SQL**:
   ```bash
   sqlite3 rocinha_entrega.db < delivery_system/migrations/change_cascade_delete.sql
   ```

---

### Opção 3: Recriar banco (CUIDADO: Perde dados)

Se você ainda não tem dados importantes em produção:

```bash
# No Railway
rm rocinha_entrega.db
python -c "from delivery_system.database import init_db; init_db()"
```

Isso cria um banco novo com as constraints corretas.

---

## ✅ Como Verificar se Funcionou

Após aplicar, teste excluindo uma rota:

1. Crie uma rota de teste
2. Adicione receita e despesa nela
3. Exclua a rota via `/deletar_rota`
4. Verifique relatórios: receitas e despesas devem ter sumido

---

## 🔙 Rollback (se necessário)

Se algo der errado, a migração cria backup automático:
```
rocinha_entrega.db.backup_YYYYMMDD_HHMMSS
```

Para restaurar:
```bash
cp rocinha_entrega.db.backup_YYYYMMDD_HHMMSS rocinha_entrega.db
```

---

## 📊 Impacto

✅ **Benefícios**:
- Relatórios sempre corretos
- Não há "lixo" de rotas excluídas
- Importações erradas podem ser corrigidas sem afetar DRE

⚠️ **Atenção**:
- **NÃO** exclua rotas que já foram finalizadas e pagas!
- Só exclua rotas **antes** de finalizar
- Após exclusão, dados são **irrecuperáveis** (exceto via backup)

---

## 🎯 Quando Usar

✅ **EXCLUIR rotas em casos**:
- Importação de planilha errada
- Rota duplicada por engano
- Teste de funcionalidades
- Rota criada no dia errado

❌ **NÃO EXCLUIR rotas**:
- Já finalizadas e pagas
- Com receitas/despesas confirmadas
- Histórico que precisa ser mantido

---

**Data da migração**: 21/10/2025  
**Commit**: 1423f4e  
**Status**: Pronto para aplicar
