# 📞 Sistema de Telefones para Entregas

## 🎯 Como Funciona

### **FLUXO COMPLETO:**

```
1. App SPX (celular) → 2. Scraper (extrai telefones) → 3. Banco de Dados → 4. Mapa Web (botão Contato)
```

---

## 📋 PASSO A PASSO

### **PARTE 1: Configurar ADB (Android Debug Bridge)**

**Windows:**
1. Baixe Android Platform Tools: https://developer.android.com/studio/releases/platform-tools
2. Extraia em `C:\platform-tools`
3. Adicione ao PATH do Windows ou use caminho completo

**Testar conexão:**
```powershell
adb devices
```

Deve mostrar:
```
List of devices attached
ABC123XYZ    device
```

---

### **PARTE 2: Preparar o Celular**

1. **Ative Depuração USB:**
   - Configurações → Sobre o telefone
   - Toque 7x em "Número da versão"
   - Volta → Opções do desenvolvedor
   - Ative "Depuração USB"

2. **Conecte via USB**
   - Conecte o cabo
   - Autorize o PC no popup do celular

3. **Abra o App SPX**
   - Faça login
   - Vá para aba "Pendente"
   - Deixe a lista de entregas visível

---

### **PARTE 3: Extrair Telefones**

**IMPORTANTE: Você precisa ajustar as coordenadas da tela primeiro!**

#### **3.1. Descobrir Coordenadas (FAZER UMA VEZ):**

```powershell
# Inicia captura de eventos de toque
adb shell getevent

# Toque nos seguintes locais no app SPX:
# 1. Primeira entrega da lista
# 2. Ícone de telefone
# 3. Botão voltar

# Para cada toque, anote os valores de ABS_MT_POSITION_X e ABS_MT_POSITION_Y
```

Converta os valores hexadecimais para coordenadas:
```python
# Exemplo: 0x0000012c (hex) = 300 (decimal)
x = int("0x0000012c", 16)  # 300
y = int("0x00000190", 16)  # 400
```

#### **3.2. Atualizar Coordenadas no Script:**

Edite `spx_scraper.py`, linha ~90:
```python
COORDS = {
    "first_delivery": (300, 400),    # ← Suas coordenadas aqui
    "phone_icon": (620, 400),        # ← Suas coordenadas aqui
    "back_button": (50, 100),        # ← Suas coordenadas aqui
}
```

#### **3.3. Executar Scraper:**

```powershell
# Certifique-se que o app SPX está aberto e na tela "Pendente"
python spx_scraper.py
```

**O script vai:**
- ✅ Verificar conexão ADB
- ✅ Para cada entrega visível:
  - Clicar na entrega
  - Clicar no ícone de telefone
  - Extrair o número
  - Voltar para lista
- ✅ Salvar tudo em `phones.json`

**Resultado:**
```json
{
  "AT202510157EM37": "21999561491",
  "BR252677984267": "21987654321",
  "BR255707102964": null
}
```

---

### **PARTE 4: Importar para o Banco de Dados**

```powershell
# Importa telefones do phones.json para o banco
python import_phones.py

# Ou especifique outro arquivo:
python import_phones.py --file meus_telefones.json
```

**Resultado:**
```
📂 Lendo phones.json...
   Total de registros: 11

✅ AT202510157EM37: 21999561491
✅ BR252677984267: 21987654321
⚠️  BR255707102964: Pacote não encontrado no banco

====================================
✅ Importação concluída!
   Atualizados: 10
   Não encontrados: 1
====================================
```

---

### **PARTE 5: Testar no Mapa**

1. Acesse o mapa: `https://entrega-web.onrender.com/map/1/123456`
2. Clique em um pin
3. Agora tem **3 botões**:
   - 🧭 Navegar (Google Maps)
   - 📞 Contato (WhatsApp) ← **NOVO!**
   - ✓ Entregar (Telegram Bot)

4. Clique "📞 Contato":
   - Abre WhatsApp Web/App
   - Conversa com o número do destinatário
   - Motorista pode avisar sobre atraso, confirmar endereço, etc.

---

## 🔧 Troubleshooting

### **ADB não encontra dispositivo:**
```powershell
# Reinstale drivers USB do celular
# Ou use modo "Transferência de arquivos" em vez de "Apenas carregamento"
```

### **Coordenadas erradas (clica no lugar errado):**
```powershell
# Recapture as coordenadas com getevent
# Ajuste os valores no script
```

### **Telefone não extraído:**
```
# Verifique se o popup de telefone aparece na tela
# Pode estar fora da área visível (precisa scroll)
```

### **Scraping muito lento:**
```python
# Reduza os time.sleep() no script
# Cuidado para não ir rápido demais e perder dados
```

---

## 🚀 Automação Futura (Ideias)

### **Opção 1: Adicionar coluna "Telefone" na planilha de importação**
- Mais simples
- Sem necessidade de scraping
- Trabalho manual de copiar telefones

### **Opção 2: API da SPX (se existir)**
- 100% automático
- Sempre atualizado
- Precisa de parceria/autorização

### **Opção 3: OCR + Screenshot**
- Mais robusto que coordenadas fixas
- Funciona mesmo se layout mudar
- Requer bibliotecas de OCR (Tesseract)

---

## 📝 Notas Importantes

⚠️ **Legalidade:** Certifique-se de que o scraping está de acordo com os termos de uso do app SPX

⚠️ **Privacidade:** Telefones são dados sensíveis - use apenas para fins de entrega

⚠️ **Manutenção:** Se o app SPX atualizar o layout, as coordenadas precisarão ser reajustadas

✅ **Backup:** Sempre salve o `phones.json` antes de reprocessar

---

## 🎯 Resultado Final

**No popup do mapa:**
```
┌─────────────────────────────────┐
│ BR252677984267                  │
│ Rua Barata Ribeiro, 559         │
│                                 │
│ [🧭 Navegar] [📞 Contato] [✓ Entregar] │
└─────────────────────────────────┘
```

**Fluxo de uso:**
1. Motorista chega no local
2. Destinatário não está
3. Clica "📞 Contato"
4. WhatsApp abre automaticamente
5. Envia mensagem: "Olá, estou aqui com sua encomenda!"
6. Destinatário desce/responde
7. Motorista completa a entrega

---

**Pronto! Sistema de telefones completo!** 🎉
