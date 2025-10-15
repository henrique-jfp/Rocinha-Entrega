#!/usr/bin/env python3
"""Force delete webhook and check bot status"""
import requests
import sys

# Token do bot (cole aqui o token correto do Render Environment Variables)
BOT_TOKEN = input("Cole o BOT_TOKEN aqui: ").strip()

def delete_webhook():
    """Force delete webhook"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    params = {"drop_pending_updates": True}
    
    print("🔧 Deletando webhook...")
    response = requests.post(url, json=params)
    print(f"Status: {response.status_code}")
    print(f"Resposta: {response.json()}")
    return response.json().get("ok", False)

def get_me():
    """Verifica se o bot está ativo"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    response = requests.get(url)
    result = response.json()
    
    if result.get("ok"):
        bot_info = result.get("result", {})
        print(f"\n✅ Bot ativo:")
        print(f"   Nome: {bot_info.get('first_name')}")
        print(f"   Username: @{bot_info.get('username')}")
        print(f"   ID: {bot_info.get('id')}")
    else:
        print(f"\n❌ Erro: {result.get('description')}")
    
    return result.get("ok", False)

def get_updates():
    """Tenta pegar updates (vai dar conflito se houver outra instância)"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 1, "limit": 1}
    
    print("\n🔍 Testando getUpdates (vai dar conflito se houver outra instância)...")
    try:
        response = requests.post(url, json=params, timeout=5)
        result = response.json()
        
        if result.get("ok"):
            print("✅ getUpdates OK - nenhuma outra instância detectada!")
        else:
            error = result.get("description", "")
            if "Conflict" in error:
                print(f"🚨 CONFLITO DETECTADO: {error}")
                print("   Há outra instância do bot rodando!")
            else:
                print(f"❌ Erro: {error}")
    except Exception as e:
        print(f"❌ Erro na requisição: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("🤖 DIAGNÓSTICO DE CONFLITO DO BOT TELEGRAM")
    print("=" * 60)
    
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        print("❌ Token inválido!")
        sys.exit(1)
    
    # Testa o bot
    if not get_me():
        print("\n❌ Token inválido ou bot não encontrado!")
        sys.exit(1)
    
    # Deleta webhook
    delete_webhook()
    
    # Testa conflitos
    get_updates()
    
    print("\n" + "=" * 60)
    print("✅ Diagnóstico concluído!")
    print("=" * 60)
