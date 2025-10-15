#!/usr/bin/env python3
"""Script para limpar webhook do Telegram e forçar polling"""
import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "8239655636:AAEQEs7-yx6onNJ-59eJFb8EmN9YcITlmY")

def clear_webhook():
    """Remove qualquer webhook configurado"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    params = {"drop_pending_updates": True}
    
    response = requests.post(url, json=params)
    result = response.json()
    
    print(f"Status: {response.status_code}")
    print(f"Resultado: {result}")
    
    if result.get("ok"):
        print("✅ Webhook removido com sucesso!")
    else:
        print(f"❌ Erro: {result.get('description')}")

def check_webhook():
    """Verifica status do webhook"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    response = requests.get(url)
    result = response.json()
    
    print(f"\n📊 Informações do Webhook:")
    print(f"URL: {result.get('result', {}).get('url', 'Nenhum')}")
    print(f"Pending Updates: {result.get('result', {}).get('pending_update_count', 0)}")

if __name__ == "__main__":
    print("🔧 Limpando configuração de webhook...\n")
    clear_webhook()
    check_webhook()
