# 🚀 Como Aplicar a Migração CASCADE no Railway (FÁCIL)

## ❌ Não consegue achar o terminal no Railway?

Não se preocupe! Existem 2 jeitos super fáceis de aplicar a migração:

---

## ✅ **MÉTODO 1: Variável de Ambiente (MAIS FÁCIL)**

### Passo a Passo:

1. **Acesse o Railway**:
   - Vá em: https://railway.app
   - Entre no projeto `rocinha-entrega-production`

2. **Adicione Variável de Ambiente**:
   - Clique no **serviço** (card do app)
   - Vá em **"Variables"** (no menu lateral ou superior)
   - Clique em **"+ New Variable"** ou **"Raw Editor"**
   - Adicione:
     ```
     RUN_MIGRATION=true
     ```
   - Clique em **"Save"** ou **"Deploy"**

3. **Aguarde o Deploy**:
   - O Railway vai fazer redeploy automaticamente
   - A migração vai rodar no startup
   - Veja os logs em **"Deployments"** → **"View Logs"**
   - Procure por: `✅ Migração aplicada com sucesso!`

4. **Remova a Variável** (depois que funcionar):
   - Volte em **"Variables"**
   - Delete `RUN_MIGRATION=true`
   - Isso evita rodar a migração toda vez

✅ **Pronto!** A migração foi aplicada!

---

## ✅ **MÉTODO 2: Recriar o Banco (MAIS SIMPLES)**

Se você ainda não tem dados importantes em produção:

### Passo a Passo:

1. **Delete o Volume do Banco**:
   - No Railway, vá no serviço
   - Procure por **"Volumes"**, **"Storage"** ou **"Data"**
   - Se tiver algum volume SQLite, **delete**

2. **Ou delete o arquivo diretamente**:
   - Se conseguir acessar o shell/terminal:
     ```bash
     rm rocinha_entrega.db
     ```

3. **Faça Redeploy**:
   - O banco será recriado automaticamente
   - Já vai ter a estrutura correta com CASCADE

✅ **Pronto!** Banco novo com estrutura correta!

---

## 🔍 **Como Verificar se Funcionou**

Depois de aplicar, teste:

1. Importe uma rota com pacotes
2. Adicione uma receita e despesa nela
3. Exclua a rota com `/deletar_rota`
4. Veja `/relatorio` - receitas e despesas devem ter sumido ✅

---

## 📊 **Comparação dos Métodos**

| Método | Facilidade | Perde Dados? | Tempo |
|--------|------------|--------------|-------|
| **1. Variável RUN_MIGRATION** | ⭐⭐⭐⭐⭐ | ❌ Não | ~2 min |
| **2. Recriar Banco** | ⭐⭐⭐⭐ | ✅ Sim | ~1 min |

---

## ⚠️ **IMPORTANTE**

**Só use o Método 2 (recriar banco) se:**
- Ainda está em testes
- Não tem dados importantes em produção
- Pode perder rotas/pacotes existentes

**Use o Método 1 (variável) se:**
- Já tem dados em produção
- Quer manter tudo
- Quer aplicar só a migração

---

## 💡 **Dica Extra**

Se mesmo assim não conseguir, me avisa que eu tento outra solução! 😊

Posso:
- Criar um comando `/migrar` no bot
- Adicionar migração automática no próximo deploy
- Ajudar a encontrar o terminal no Railway

---

**Última atualização**: 22/10/2025  
**Status**: ✅ Pronto para usar
