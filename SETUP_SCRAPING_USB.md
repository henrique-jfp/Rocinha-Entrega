# 🔌 Setup Completo - Scraping com Cabo USB

## 📋 Checklist de Requisitos

- [ ] S23+ com cabo USB conectado ao PC
- [ ] Android Platform Tools (ADB) instalado
- [ ] Depuração USB ativada no celular
- [ ] App SPX Motorista instalado
- [ ] Python configurado no projeto

---

## 🚀 PASSO 1: Instalar Android Platform Tools

### Download

1. Acesse: https://developer.android.com/studio/releases/platform-tools
2. Baixe **"SDK Platform-Tools for Windows"**
3. Extraia a pasta `platform-tools` em um local fixo (ex: `C:\platform-tools`)

### Adicionar ao PATH (Recomendado)

Isso permite usar `adb` de qualquer pasta:

**PowerShell (Admin):**
```powershell
# Adicionar ao PATH do sistema
$oldPath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$newPath = $oldPath + ';C:\platform-tools'
[Environment]::SetEnvironmentVariable('Path', $newPath, 'Machine')

# Reinicie o PowerShell após isso
```

**OU Manualmente:**
1. Pesquise "Variáveis de Ambiente" no Windows
2. Em "Variáveis do sistema", edite `Path`
3. Adicione: `C:\platform-tools`
4. Clique OK e reinicie o PowerShell

### Testar Instalação

```powershell
adb --version
```

Deve mostrar: `Android Debug Bridge version 1.0.XX`

---

## 📱 PASSO 2: Ativar Depuração USB no S23+

### 1. Ativar Opções do Desenvolvedor

1. **Configurações** → **Sobre o telefone**
2. Toque **7 vezes** em "Número da versão" ou "Versão da compilação"
3. Deve aparecer: _"Você agora é um desenvolvedor!"_

### 2. Ativar Depuração USB

1. **Configurações** → **Opções do desenvolvedor**
2. Ative **Opções do desenvolvedor** (chave no topo)
3. Ative **Depuração USB**
4. Confirme no popup

### 3. Conectar Cabo USB

1. Conecte o S23+ ao PC com cabo USB
2. Selecione **"Transferência de arquivos"** na notificação do celular
3. Deve aparecer popup: _"Permitir depuração USB?"_
4. ✅ Marque **"Sempre permitir neste computador"**
5. Toque **OK**

### 4. Verificar Conexão

```powershell
adb devices
```

**Deve mostrar:**
```
List of devices attached
R5CR30XXXXX    device
```

✅ Se aparecer `device` = **FUNCIONOU!**

❌ Se aparecer `unauthorized` = Olhe a tela do celular e autorize

❌ Se não aparecer nada = Verifique cabo USB e drivers

---

## 🛠️ PASSO 3: Calibrar Coordenadas do SPX App

O scraper precisa saber **onde tocar** na tela do seu S23+.

### 1. Abrir App SPX e Deixar na Lista de Entregas

1. Abra o **SPX Motorista**
2. Vá até a tela de **"Pendentes"** (lista de entregas)
3. **Deixe o app aberto nessa tela**

### 2. Capturar Coordenadas dos Toques

Vamos descobrir onde o scraper deve tocar:

**PowerShell:**
```powershell
# Tira screenshot da tela do celular
adb shell screencap -p /sdcard/screen.png
adb pull /sdcard/screen.png screen.png

# Abre a imagem
start screen.png
```

Agora você verá a tela do SPX. Use uma ferramenta de captura do Windows para medir coordenadas:

1. Aperte `Win + Shift + S` (Ferramenta de Captura)
2. Capture a área
3. Cole no Paint (`Ctrl + V`)
4. Passe o mouse sobre:
   - **Primeira entrega da lista** → Anote X, Y (canto inferior esquerdo do Paint)
   - **Ícone de telefone** (quando abre a entrega) → Anote X, Y
   - **Botão voltar** (seta no topo) → Anote X, Y

### 3. Atualizar Coordenadas no Script

Abra `spx_scraper.py` e atualize as coordenadas na linha ~171:

```python
COORDS = {
    "first_delivery": (300, 400),    # ← SUBSTITUA pelos valores capturados
    "phone_icon": (620, 400),        # ← SUBSTITUA
    "back_button": (50, 100),        # ← SUBSTITUA
}
```

**Exemplo com valores reais:**
```python
COORDS = {
    "first_delivery": (540, 650),    # Meio da primeira entrega
    "phone_icon": (980, 180),        # Ícone de telefone no topo
    "back_button": (80, 120),        # Seta voltar
}
```

### 4. Testar Um Toque

```powershell
# Teste tocar na primeira entrega
adb shell input tap 540 650

# Deve abrir os detalhes da entrega!
```

Se abriu corretamente, **as coordenadas estão certas!** ✅

Se tocou no lugar errado, ajuste os valores e teste novamente.

---

## 🎬 PASSO 4: Testar Scraping Manualmente

Antes de integrar no `/importar`, vamos testar isoladamente:

### 1. Criar Arquivo de Teste

Crie `test_scraping.py`:

```python
from spx_scraper import SPXScraper

# Códigos de rastreio que você quer buscar telefones
tracking_codes = [
    "AT202510157EM37",
    "BR252677984267",
    # Adicione alguns códigos reais da sua rota
]

scraper = SPXScraper()
results = scraper.scrape_delivery_phones(tracking_codes)
scraper.save_results(results, "phones_teste.json")

print("\n📊 Resultados:")
for code, phone in results.items():
    print(f"{code}: {phone or 'NÃO ENCONTRADO'}")
```

### 2. Executar Teste

```powershell
# 1. Certifique-se que o celular está conectado
adb devices

# 2. Abra o SPX no celular (tela de Pendentes)

# 3. Execute o teste
python test_scraping.py
```

### 3. Verificar Resultados

```powershell
# Ver arquivo gerado
cat phones_teste.json
```

Deve mostrar:
```json
{
  "AT202510157EM37": "21999561491",
  "BR252677984267": "21987654321"
}
```

✅ Se os telefones foram extraídos corretamente, **está pronto!**

---

## 🤖 PASSO 5: Usar no Bot /importar

Agora que tudo está funcionando, vamos usar no fluxo real:

### Fluxo Completo

1. **Conecte o S23+ via USB ao PC**
2. **Verifique conexão:** `adb devices`
3. **Abra SPX no celular** (tela de Pendentes)
4. **Inicie o bot localmente:**

```powershell
cd "C:\Rocinha Entrega"
python -m delivery_system.bot
```

5. **No Telegram, envie `/importar`**
6. **Envie a planilha Excel**
7. **Bot vai perguntar:** _"Deseja extrair telefones do SPX agora?"_
8. **Responda:** `Sim`
9. **Bot vai pedir:** _"Conecte o celular e abra o SPX..."_
10. **Confirme:** `Pronto`
11. **Aguarde o scraping** (não toque no celular!)
12. **Bot confirma:** _"✅ Telefones extraídos: X pacotes"_

---

## 🆘 Solução de Problemas

### "adb: command not found"
- ✅ Instale Android Platform Tools
- ✅ Adicione ao PATH
- ✅ Reinicie PowerShell

### "no devices/emulators found"
```powershell
# Reiniciar servidor ADB
adb kill-server
adb start-server
adb devices
```

- ✅ Verifique cabo USB (tente outra porta)
- ✅ Olhe notificação do celular (deve estar em "Transferência de arquivos")
- ✅ Autorize depuração USB no popup do celular

### "device unauthorized"
- ✅ Olhe a tela do S23+ - deve ter popup pedindo autorização
- ✅ Marque "Sempre permitir" e toque OK

### Scraper toca nos lugares errados
- ✅ Recalibre as coordenadas (Passo 3)
- ✅ Use `adb shell input tap X Y` para testar cada coordenada
- ✅ Valores típicos para S23+: entre 0-1080 (largura) e 0-2340 (altura)

### "Telefone não encontrado"
- ✅ Verifique se SPX mostra telefone na tela (alguns pacotes não têm)
- ✅ Ajuste regex patterns em `extract_phone_from_screen()`
- ✅ Teste manualmente: `adb shell uiautomator dump` e veja o XML gerado

### Scraper é muito lento
- ✅ Reduza `time.sleep()` nos toques (cuidado para não ir rápido demais)
- ✅ Use cabo USB 3.0 (mais rápido que 2.0)

---

## ✅ Checklist Final

Antes de rodar no bot, confirme:

- [ ] `adb devices` mostra seu celular como `device`
- [ ] Coordenadas calibradas (toques funcionam corretamente)
- [ ] `test_scraping.py` extrai telefones com sucesso
- [ ] SPX aberto na tela de Pendentes
- [ ] Bot rodando localmente (`python -m delivery_system.bot`)

---

## 🎯 Comandos Úteis

```powershell
# Verificar conexão
adb devices

# Screenshot do celular
adb shell screencap -p /sdcard/screen.png
adb pull /sdcard/screen.png .

# Testar toque em coordenada
adb shell input tap 540 650

# Ver hierarquia de UI (para debug)
adb shell uiautomator dump
adb pull /sdcard/window_dump.xml .

# Reiniciar ADB (se travar)
adb kill-server
adb start-server

# Desconectar (quando terminar)
adb disconnect
```

---

## 🚀 Próximos Passos

Depois que funcionar localmente:

1. ✅ Testar com rota completa (20-30 pacotes)
2. ✅ Validar telefones no mapa (botão Contato deve aparecer)
3. ✅ Decidir se vai rodar localmente ou tentar automatizar no servidor
4. ✅ Documentar coordenadas específicas do seu S23+

---

**🎉 Pronto! Agora você tem scraping automático integrado ao `/importar`!**
