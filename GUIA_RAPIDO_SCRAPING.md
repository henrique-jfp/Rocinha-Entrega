# ⚡ GUIA RÁPIDO - Scraping no /importar

## 🎯 Checklist Antes de Importar Rota

```powershell
# 1. Verificar ADB
adb devices
# Deve mostrar: R5CR30XXXXX    device

# 2. Testar coordenadas (opcional)
adb shell input tap 540 650  # Ajuste para suas coordenadas

# 3. Abrir SPX no celular (tela de Pendentes)

# 4. Iniciar bot
cd "C:\Rocinha Entrega"
python -m delivery_system.bot
```

---

## 🤖 Fluxo no Telegram

1. `/importar`
2. Enviar planilha Excel
3. Bot: _"Deseja extrair telefones do SPX agora?"_
   - Responda: `Sim`
4. Bot: _"Conecte o celular via USB, abra o SPX..."_
   - Confirme: `Pronto`
5. **Aguarde** (não toque no celular!)
6. Bot: _"✅ Telefones extraídos: X pacotes"_

---

## 🔧 Primeira Vez? Siga Esta Ordem

1. ✅ **Instalar ADB** (SETUP_SCRAPING_USB.md - Passo 1)
2. ✅ **Ativar Depuração USB** (SETUP_SCRAPING_USB.md - Passo 2)
3. ✅ **Calibrar Coordenadas** (SETUP_SCRAPING_USB.md - Passo 3)
4. ✅ **Testar Scraping** (rode `python test_scraping.py`)
5. ✅ **Usar no Bot** (fluxo acima)

---

## 🆘 Problemas Comuns

| Erro | Solução |
|------|---------|
| `adb: command not found` | Instale Platform Tools + adicione ao PATH |
| `no devices found` | Conecte cabo USB + autorize depuração |
| `device unauthorized` | Olhe tela do celular e autorize |
| Toca lugares errados | Recalibre coordenadas (Passo 3) |
| Telefones não encontrados | Verifique SPX mostra telefone na tela |

---

## 📁 Arquivos Importantes

- `spx_scraper.py` - Script principal (ajustar COORDS linha ~171)
- `test_scraping.py` - Teste isolado antes de usar no bot
- `SETUP_SCRAPING_USB.md` - Guia completo passo a passo
- `delivery_system/bot.py` - Integração no /importar (já configurado)

---

## 📞 Telefones Aparecem Onde?

Após scraping bem-sucedido:

1. ✅ **Banco de dados** - Campo `phone` na tabela `packages`
2. ✅ **Mapa** - Botão "📞 Contato" no popup de cada entrega
3. ✅ **WhatsApp** - Abre conversa automática ao clicar

---

## 💡 Dica Pro

Sempre rode `python test_scraping.py` primeiro quando:
- Trocar de celular
- Atualizar app SPX
- Interface do SPX mudar

Isso evita erros durante importação real de rotas!
