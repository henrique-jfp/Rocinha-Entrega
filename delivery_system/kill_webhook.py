#!/usr/bin/env python3
"""
Script para limpar webhooks e garantir que não há outras instâncias do bot rodando.
Deve ser executado antes de iniciar o bot.
"""
import os
import sys
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ BOT_TOKEN não configurado")
    sys.exit(1)

def delete_webhook():
    """Remove qualquer webhook configurado"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    try:
        response = requests.post(url, json={"drop_pending_updates": True}, timeout=10)
        if response.status_code == 200:
            print("✅ Webhook removido com sucesso")
            return True
        else:
            print(f"⚠️ Falha ao remover webhook: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Erro ao remover webhook: {e}")
        return False

def close_existing_connections():
    """Tenta fechar conexões existentes fazendo um getUpdates com offset alto"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        # Faz um getUpdates com offset muito alto para "limpar" qualquer conexão antiga
        response = requests.post(url, json={"offset": -1, "timeout": 1}, timeout=5)
        if response.status_code == 200:
            print("✅ Conexões antigas fechadas")
            return True
        else:
            print(f"⚠️ Falha ao fechar conexões: {response.text}")
            return False
    except Exception as e:
        print(f"⚠️ Erro ao fechar conexões (pode ser normal): {e}")
        return True  # Não é crítico

if __name__ == "__main__":
    print("🧹 Limpando webhooks e conexões antigas...")
    delete_webhook()
    close_existing_connections()
    print("✅ Limpeza concluída. Bot pode iniciar.")
