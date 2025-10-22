#!/usr/bin/env python3
"""
Script de startup que roda ANTES do bot iniciar.
Aplica migrações automaticamente se necessário.
"""

import os
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

def run_migrations():
    """Aplica migrações pendentes"""
    print("=" * 60)
    print("🔍 Verificando migrações pendentes...")
    print("=" * 60)
    
    # Verifica se deve rodar migração
    run_migration = os.getenv("RUN_MIGRATION", "false").lower() == "true"
    
    if run_migration:
        print("✅ RUN_MIGRATION=true detectado")
        print("🔄 Aplicando migração CASCADE DELETE...")
        
        try:
            from delivery_system.apply_cascade_migration import apply_migration
            success = apply_migration()
            
            if success:
                print("✅ Migração aplicada com sucesso!")
                # Remove a flag para não rodar novamente
                print("💡 Dica: Remova a variável RUN_MIGRATION do Railway")
            else:
                print("❌ Migração falhou!")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao aplicar migração: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print("ℹ️  Nenhuma migração pendente")
        print("💡 Para forçar migração, adicione variável: RUN_MIGRATION=true")
    
    print("=" * 60)
    return True

if __name__ == "__main__":
    # Roda migrações
    if not run_migrations():
        print("⚠️ Migração falhou, mas continuando inicialização...")
    
    # Inicia o bot normalmente
    print("\n🤖 Iniciando bot...")
    from delivery_system.bot import main
    main()
