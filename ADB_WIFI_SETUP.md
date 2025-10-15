# 🔧 Configurar ADB via Wi-Fi (Sem Cabo!)

## Requisitos
- ✅ S23+ e PC no **mesmo Wi-Fi**
- ✅ Android Platform Tools instalado
- ✅ Depuração USB ativada (mesmo sem cabo)

## 🚀 Setup Inicial (Fazer UMA VEZ)

### 1. Ativar Depuração Wireless no S23+

**Android 11+** tem depuração wireless nativa:

1. Vá em **Configurações** → **Opções do desenvolvedor**
2. Ative **Depuração wireless** (Wireless debugging)
3. Toque em **Depuração wireless**
4. Toque em **Parear dispositivo com código de pareamento**
5. **Anote o IP e a porta** (ex: `192.168.1.100:37845`)
6. **Anote o código de pareamento** (6 dígitos)

### 2. Parear no PC (PowerShell)

```powershell
# Navegue até a pasta do ADB
cd "C:\platform-tools"  # Ajuste para onde você instalou

# Pareie usando o IP e porta que apareceu no celular
.\adb.exe pair 192.168.1.100:37845

# Cole o código de pareamento quando pedir
# Exemplo: 123456
```

✅ Deve aparecer: **"Successfully paired to..."**

### 3. Conectar via Wi-Fi

```powershell
# Use o IP que aparece em "Depuração wireless" (porta diferente, geralmente 5555)
.\adb.exe connect 192.168.1.100:5555
```

✅ Deve aparecer: **"connected to 192.168.1.100:5555"**

### 4. Verificar Conexão

```powershell
.\adb.exe devices
```

Deve mostrar:
```
List of devices attached
192.168.1.100:5555      device
```

---

## 🎯 Usar Scraper via Wi-Fi

Agora o scraper funciona **sem cabo nenhum**!

```powershell
# Navegue até a pasta do projeto
cd "C:\Rocinha Entrega"

# Execute o scraper normalmente
python spx_scraper.py
```

---

## 🔄 Reconectar (Próximas Vezes)

Após reiniciar o celular ou PC:

```powershell
cd "C:\platform-tools"
.\adb.exe connect 192.168.1.100:5555  # Use o IP do SEU celular
```

---

## 🆘 Solução de Problemas

### "cannot connect to 192.168.1.100:5555"
- ✅ Confirme que **Depuração wireless** está ATIVA no celular
- ✅ Confirme que ambos estão no **mesmo Wi-Fi**
- ✅ Use o **IP correto** (veja em Configurações → Sobre o telefone → Status)

### "device unauthorized"
- ✅ Olhe a tela do celular - deve aparecer popup pedindo autorização
- ✅ Marque "Sempre permitir deste computador" e toque em OK

### "no devices/emulators found"
```powershell
.\adb.exe kill-server
.\adb.exe start-server
.\adb.exe connect 192.168.1.100:5555
```

---

## 📱 Encontrar IP do S23+

1. **Configurações** → **Conexões** → **Wi-Fi**
2. Toque na rede conectada (ícone de engrenagem)
3. Role até **Endereço IP**
4. Anote (ex: `192.168.1.100`)

Ou use:
```powershell
# Se já estiver conectado via cabo
.\adb.exe shell ip addr show wlan0
```

---

## ⚡ Dicas

- 🔋 Mantenha o celular carregando durante scraping
- 📶 Wi-Fi 5GHz é mais rápido que 2.4GHz
- 🔒 Desative "Desligar Wi-Fi automaticamente" nas configurações avançadas
- ⏱️ A conexão pode cair se o celular entrar em modo de economia de energia

---

## 🎬 Fluxo Completo

1. **Celular**: Ative "Depuração wireless"
2. **PC**: `adb pair IP:PORTA` (primeira vez)
3. **PC**: `adb connect IP:5555`
4. **PC**: Rode `python spx_scraper.py`
5. **Celular**: Deixe aberto no app SPX (tela de Pendentes)
6. **PC**: Aguarde scraping terminar
7. ✅ `phones.json` criado!

---

**Vantagens sobre cabo USB:**
- ✅ Mais prático (sem fio)
- ✅ Pode deixar celular carregando em qualquer lugar
- ✅ Não depende de drivers USB
- ✅ Funciona com qualquer PC na rede

**Desvantagens:**
- ⚠️ Pode ser um pouco mais lento
- ⚠️ Requer Wi-Fi estável
- ⚠️ Precisa reconectar após reiniciar
