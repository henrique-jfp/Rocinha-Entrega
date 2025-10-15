#!/usr/bin/env python3
"""
Script de teste para verificar se o scraping está funcionando
antes de usar no bot /importar
"""

from spx_scraper import SPXScraper

def main():
    print("=" * 60)
    print("🧪 TESTE DE SCRAPING - SPX Phone Extractor")
    print("=" * 60)
    print()
    
    # ⚠️ SUBSTITUA pelos códigos reais da sua próxima rota
    tracking_codes = [
        "AT202510157EM37",
        "BR252677984267",
        "BR255707102964",
    ]
    
    print("📦 Códigos que serão buscados:")
    for code in tracking_codes:
        print(f"   - {code}")
    print()
    
    print("⚠️  INSTRUÇÕES:")
    print("1. ✅ Celular conectado via USB")
    print("2. ✅ Depuração USB autorizada")
    print("3. ✅ App SPX aberto na tela de 'Pendentes'")
    print("4. ✅ NÃO toque no celular durante o teste")
    print()
    
    input("Pressione ENTER quando estiver pronto...")
    print()
    
    # Executar scraping
    scraper = SPXScraper()
    results = scraper.scrape_delivery_phones(tracking_codes)
    scraper.save_results(results, "phones_teste.json")
    
    # Exibir resultados
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DO TESTE")
    print("=" * 60)
    
    success_count = sum(1 for v in results.values() if v)
    fail_count = len(results) - success_count
    
    for code, phone in results.items():
        status = "✅" if phone else "❌"
        phone_display = phone or "NÃO ENCONTRADO"
        print(f"{status} {code}: {phone_display}")
    
    print()
    print(f"Total processado: {len(results)}")
    print(f"Com telefone: {success_count} ({success_count/len(results)*100:.1f}%)")
    print(f"Sem telefone: {fail_count} ({fail_count/len(results)*100:.1f}%)")
    print()
    print(f"💾 Resultados salvos em: phones_teste.json")
    print()
    
    if success_count == len(results):
        print("🎉 PERFEITO! Todos os telefones foram extraídos!")
        print("   Você pode usar o scraping no /importar agora.")
    elif success_count > 0:
        print("⚠️  Alguns telefones não foram encontrados.")
        print("   Possíveis causas:")
        print("   - Pacote não tem telefone cadastrado no SPX")
        print("   - Coordenadas de toque precisam ser ajustadas")
        print("   - Formato do telefone diferente do esperado")
    else:
        print("❌ ERRO! Nenhum telefone foi extraído.")
        print("   Verifique:")
        print("   1. Coordenadas em spx_scraper.py (linha ~171)")
        print("   2. App SPX está aberto na tela certa")
        print("   3. Conexão ADB: rode 'adb devices'")

if __name__ == "__main__":
    main()
