# 🧪 Instruções para Testar o Mapa Interativo

## ⏱️ Timeline
- ✅ **02:14** - Código atualizado com logs detalhados
- ✅ **02:17** - Deploy iniciado (commit a5142d7)
- 🔄 **02:17-02:20** - Railway redeployando (~3 minutos)
- ⏳ **02:20+** - **VOCÊ AQUI** - Teste agora

## 📱 Teste do Browser Console

### Passo 1: Abrir o Mapa
```
Acesse: https://rocinha-entrega-production.up.railway.app/map/11/7739751735
```

### Passo 2: Abrir DevTools
```
- Windows/Linux: F12 ou Ctrl+Shift+I
- Mac: Cmd+Option+I
```

### Passo 3: Ir para a Aba "Console"
Procure por mensagens começando com:
- 🚀
- 📍
- ✅
- 📡
- ❌

### Passo 4: Verificar Logs (nesta ordem)

**✅ ESPERADO - Se Tudo OK:**
```
🚀 Map script iniciado
📍 Variáveis carregadas: { routeId: 11, driverId: 7739751735, botUsername: "...", baseUrl: "https://..." }
✅ Mapa Leaflet inicializado
🔍 Carregando pacotes de: https://rocinha-entrega-production.up.railway.app/route/11/packages
📡 Response status: 200 OK
✅ Dados recebidos: 15 pacotes [...]
✅ Pacotes carregados com sucesso!
```

**❌ ERRO 1 - Script não iniciou:**
```
[NÃO APARECE: "🚀 Map script iniciado"]
```
→ **Problema**: Leaflet CDN não carregou ou erro de sintaxe
→ **Solução**: Verificar Network tab, procurar 404 no leaflet.js

**❌ ERRO 2 - Erro na inicialização:**
```
❌ Erro fatal no map script: [mensagem]
```
→ **Problema**: Erro ao criar mapa ou camadas Leaflet
→ **Solução**: Verificar mensagem específica do erro

**❌ ERRO 3 - Erro ao carregar pacotes:**
```
❌ Erro HTTP: 404 [...]
```
→ **Problema**: Rota não encontrada no banco
→ **Solução**: Verificar se rota 11 existe em produção

**❌ ERRO 4 - Erro de JSON:**
```
❌ Erro ao fazer parse JSON: SyntaxError...
```
→ **Problema**: Backend retorna HTML em vez de JSON
→ **Solução**: Verificar response text (geralmente erro 500)

## 🔍 Teste da API Diretamente

Se o mapa não funcionar, teste a API diretamente:

```bash
# Terminal/PowerShell
curl "https://rocinha-entrega-production.up.railway.app/route/11/packages" | python -m json.tool
```

**Resultado esperado:**
```json
[
  {
    "id": 1,
    "tracking_code": "SPX123456",
    "address": "Rua das Flores, 123",
    "neighborhood": "Centro",
    "latitude": -22.9,
    "longitude": -43.2,
    "status": "pending"
  },
  ...
]
```

## 📊 Verificar Railway Logs

Acesse: https://dashboard.railway.app → Rocinha-Entrega → Logs

Procure por:
```
🔍 GET /route/11/packages - Buscando pacotes...
✅ Rota encontrada: [name]
📦 15 pacotes encontrados
✅ Retornando 15 pacotes serializados
```

Ou erro:
```
❌ Rota 11 não encontrada!
❌ Erro ao serializar pacote 1: [error details]
❌ Erro geral em get_route_packages: [error details]
```

## 💻 Debug Local (Advanced)

Se quiser testar localmente com PostgreSQL:

```bash
cd "c:\Rocinha Entrega"

# Testar endpoint
python test_map_endpoint.py

# Ou testar FastAPI diretamente
cd delivery_system
python -m uvicorn app:create_app --reload --port 8001
# Depois: curl http://localhost:8001/route/11/packages
```

## 🎯 Próximas Ações Baseadas em Resultado

| Resultado | Ação |
|-----------|------|
| ✅ Mapa carrega, pacotes visíveis | **PROBLEMA RESOLVIDO** - Notifique o time |
| ❌ Script não inicia (sem logs) | Verificar Leaflet CDN, limpar cache browser |
| ❌ Erro HTTP 404 | Rota 11 não existe - criar rota de teste |
| ❌ Erro HTTP 500 | Backend crash - verificar Railway logs |
| ❌ JSON parse error | Possível erro de serialização - verificar logs detalhados |

## 🚀 Se Tudo Ok:
Parabéns! O mapa está funcionando. Agora você pode:
1. Criar mais rotas para teste
2. Importar pacotes reais
3. Acompanhar entregas em tempo real

---

**Criado em**: 2025-10-17 02:17 UTC
**Status**: Aguardando redeploy Railway
**Próximo passo**: Execute esta checklist em ~3 minutos
