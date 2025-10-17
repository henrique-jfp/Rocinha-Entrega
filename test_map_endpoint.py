#!/usr/bin/env python3
"""
Script para testar o endpoint /route/{route_id}/packages
Simula a requisição que o mapa faz
"""
import os
import sys
from dotenv import load_dotenv

# Adicionar delivery_system ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'delivery_system'))

load_dotenv()

# Verificar se DATABASE_URL está configurada
db_url = os.getenv('DATABASE_URL')
if not db_url:
    print("❌ DATABASE_URL não configurada!")
    print("ℹ️ Teste local usa SQLite, que não funciona sem migração")
    print("\n📋 Para testar em produção, use:")
    print("   curl https://rocinha-entrega-production.up.railway.app/route/11/packages")
    sys.exit(1)

print(f"✅ DATABASE_URL: {db_url[:50]}...")

from app import create_app
from database import SessionLocal, Route, Package

# Criar app
app = create_app()

# Testar endpoint diretamente
print("\n🔍 Testando /route/11/packages...")

try:
    db = SessionLocal()
    
    # Verificar se rota 11 existe
    route = db.query(Route).filter(Route.id == 11).first()
    if route:
        print(f"✅ Rota 11 encontrada: {route.name}")
        
        # Contar pacotes
        packages = db.query(Package).filter(Package.route_id == 11).all()
        print(f"📦 {len(packages)} pacotes encontrados")
        
        if packages:
            for p in packages[:3]:
                print(f"  - {p.tracking_code}: {p.address} ({p.status})")
                print(f"    Lat/Lng: {p.latitude}/{p.longitude}")
        else:
            print("⚠️ Nenhum pacote encontrado na rota 11")
    else:
        print("❌ Rota 11 não encontrada")
    
    db.close()
    
except Exception as e:
    print(f"❌ Erro ao testar: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✅ Teste concluído!")
print("\n💡 Para testar em produção:")
print("   curl https://rocinha-entrega-production.up.railway.app/route/11/packages | python -m json.tool")
