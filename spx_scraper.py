#!/usr/bin/env python3
"""
Script para extrair telefones dos pacotes do App SPX Motorista Parceiro
usando automação com PyAutoGUI ou ADB (Android Debug Bridge)

IMPORTANTE: Rode este script ENQUANTO o app SPX está aberto no emulador/celular
"""

import time
import re
from pathlib import Path
from typing import Dict, List, Optional
import json

# Opções de implementação:
# 1. PyAutoGUI (controla mouse/teclado do PC)
# 2. ADB (Android Debug Bridge - controla celular via USB)
# 3. Selenium + Chrome Remote Debugging (se SPX tiver versão web)

# Para este MVP, vamos usar ADB (mais confiável)
import subprocess


class SPXScraper:
    """Scraper para extrair telefones do app SPX via ADB"""
    
    def __init__(self):
        self.adb_path = "adb"  # ou caminho completo: C:\\platform-tools\\adb.exe
        self.package_name = "com.speedpak.motorista"  # Nome do pacote SPX (exemplo)
        
    def check_adb_connection(self) -> bool:
        """Verifica se há dispositivo conectado via ADB"""
        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True,
                text=True,
                timeout=5
            )
            devices = result.stdout.strip().split('\n')[1:]  # Pula header
            connected = [d for d in devices if d.strip() and 'device' in d]
            
            if not connected:
                print("❌ Nenhum dispositivo Android conectado!")
                print("   1. Conecte o celular via USB")
                print("   2. Ative 'Depuração USB' nas configurações de desenvolvedor")
                print("   3. Rode: adb devices")
                return False
            
            print(f"✅ Dispositivo conectado: {connected[0]}")
            return True
            
        except FileNotFoundError:
            print("❌ ADB não encontrado!")
            print("   Baixe Android Platform Tools:")
            print("   https://developer.android.com/studio/releases/platform-tools")
            return False
    
    def tap_screen(self, x: int, y: int):
        """Simula toque na tela"""
        subprocess.run([self.adb_path, "shell", "input", "tap", str(x), str(y)])
        time.sleep(0.5)
    
    def get_screen_text(self) -> str:
        """Captura texto da tela atual usando OCR ou UI dump"""
        # Opção 1: UI Dump (XML da hierarquia de views)
        subprocess.run([self.adb_path, "shell", "uiautomator", "dump"])
        subprocess.run([self.adb_path, "pull", "/sdcard/window_dump.xml", "screen_dump.xml"])
        
        with open("screen_dump.xml", "r", encoding="utf-8") as f:
            xml_content = f.read()
        
        return xml_content
    
    def extract_phone_from_screen(self) -> Optional[str]:
        """Extrai telefone da tela atual"""
        xml = self.get_screen_text()
        
        # Regex para encontrar telefones brasileiros
        # Formatos: (21) 99956-1491, 21999561491, +5521999561491
        phone_patterns = [
            r'\+55\s*\d{2}\s*\d{4,5}-?\d{4}',  # +55 21 99956-1491
            r'\(\d{2}\)\s*\d{4,5}-?\d{4}',     # (21) 99956-1491
            r'\d{2}\s*\d{4,5}-?\d{4}',         # 21 99956-1491
            r'\d{10,11}',                       # 21999561491
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, xml)
            if match:
                phone = match.group(0)
                # Normaliza para formato limpo: apenas dígitos
                phone_clean = re.sub(r'\D', '', phone)
                if len(phone_clean) >= 10:
                    return phone_clean
        
        return None
    
    def scrape_delivery_phones(self, tracking_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        Scrape telefones de uma lista de códigos de rastreio
        
        PROCESSO:
        1. Para cada código de rastreio
        2. Procura na lista de entregas
        3. Clica na entrega
        4. Clica no ícone de telefone
        5. Extrai o número
        6. Volta para lista
        """
        
        if not self.check_adb_connection():
            return {}
        
        print("🚀 Iniciando scraping de telefones...")
        print("⚠️  ATENÇÃO: NÃO TOQUE NO CELULAR DURANTE O PROCESSO!")
        print()
        
        results = {}
        
        # Coordenadas (você precisará ajustar para sua tela)
        # Use 'adb shell getevent' para capturar coordenadas
        COORDS = {
            "first_delivery": (300, 400),    # Primeira entrega na lista
            "phone_icon": (620, 400),        # Ícone de telefone
            "back_button": (50, 100),        # Botão voltar
        }
        
        for i, tracking_code in enumerate(tracking_codes, 1):
            print(f"📦 [{i}/{len(tracking_codes)}] Processando: {tracking_code}")
            
            try:
                # 1. Clica na entrega (assumindo que está visível)
                # TODO: Implementar scroll se necessário
                self.tap_screen(*COORDS["first_delivery"])
                time.sleep(1)
                
                # 2. Clica no ícone de telefone
                self.tap_screen(*COORDS["phone_icon"])
                time.sleep(1)
                
                # 3. Extrai telefone da tela
                phone = self.extract_phone_from_screen()
                
                if phone:
                    print(f"   ✅ Telefone encontrado: {phone}")
                    results[tracking_code] = phone
                else:
                    print(f"   ⚠️  Telefone não encontrado")
                    results[tracking_code] = None
                
                # 4. Volta para lista
                self.tap_screen(*COORDS["back_button"])
                time.sleep(1)
                
            except Exception as e:
                print(f"   ❌ Erro: {e}")
                results[tracking_code] = None
        
        print()
        print(f"✅ Scraping concluído! {len(results)} pacotes processados.")
        return results
    
    def save_results(self, results: Dict[str, Optional[str]], output_file: str = "phones.json"):
        """Salva resultados em JSON"""
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"💾 Resultados salvos em: {output_file}")


def main():
    """Exemplo de uso"""
    
    # Lista de códigos de rastreio para buscar telefones
    tracking_codes = [
        "AT202510157EM37",
        "BR252677984267",
        "BR255707102964",
        # ... adicione mais códigos
    ]
    
    scraper = SPXScraper()
    results = scraper.scrape_delivery_phones(tracking_codes)
    scraper.save_results(results)
    
    # Exibe resultados
    print("\n📊 Resumo:")
    print(f"Total: {len(results)}")
    print(f"Com telefone: {sum(1 for v in results.values() if v)}")
    print(f"Sem telefone: {sum(1 for v in results.values() if not v)}")


if __name__ == "__main__":
    print("=" * 60)
    print("🤖 SPX Phone Scraper")
    print("=" * 60)
    print()
    print("⚠️  INSTRUÇÕES:")
    print("1. Conecte o celular via USB")
    print("2. Ative 'Depuração USB' nas configurações")
    print("3. Abra o app SPX Motorista")
    print("4. Deixe na tela de 'Pendente' com as entregas visíveis")
    print("5. NÃO toque no celular durante o processo")
    print()
    input("Pressione ENTER quando estiver pronto...")
    print()
    
    main()
