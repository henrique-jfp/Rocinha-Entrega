from database import SessionLocal, Package, Route

db = SessionLocal()
try:
    routes = db.query(Route).all()
    print(f'Total de rotas: {len(routes)}')
    
    if routes:
        for route in routes:
            pkgs = db.query(Package).filter(Package.route_id == route.id).all()
            print(f'\nRota ID: {route.id}')
            print(f'Nome: {route.name}')
            print(f'Pacotes: {len(pkgs)}')
            
            for pkg in pkgs[:3]:  # mostrar só os 3 primeiros
                print(f'  - {pkg.tracking_code}: {pkg.address} (lat={pkg.latitude}, lng={pkg.longitude})')
    else:
        print('Nenhuma rota encontrada no banco!')
finally:
    db.close()
