import requests

# Testar API local
base_url = "http://localhost:8001"

print("🔍 Testando API local...")
print()

# 1. Health check
try:
    r = requests.get(f"{base_url}/health")
    print(f"✅ Health: {r.json()}")
except Exception as e:
    print(f"❌ Health: {e}")

# 2. Route packages
try:
    r = requests.get(f"{base_url}/route/2/packages")
    data = r.json()
    print(f"✅ Pacotes da rota 2: {len(data)} pacotes")
    if data:
        print(f"   Primeiro pacote: {data[0]['tracking_code']}")
        print(f"   Coordenadas: ({data[0]['latitude']}, {data[0]['longitude']})")
except Exception as e:
    print(f"❌ Pacotes: {e}")
