from datetime import datetime
from database import SessionLocal, init_db, Route, Package


def run():
    init_db()
    db = SessionLocal()
    try:
        route = Route(name=f"Rota {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}")
        db.add(route)
        db.flush()  # get route.id

        samples = [
            {
                "tracking_code": "PKG-1001",
                "address": "Rua A, 123",
                "neighborhood": "Bairro 1",
                "latitude": -22.9068,
                "longitude": -43.1729,
            },
            {
                "tracking_code": "PKG-1002",
                "address": "Rua B, 456",
                "neighborhood": "Bairro 2",
                "latitude": -22.9133,
                "longitude": -43.2003,
            },
            {
                "tracking_code": "PKG-1003",
                "address": "Rua C, 789",
                "neighborhood": "Bairro 3",
                "latitude": -22.9235,
                "longitude": -43.2342,
            },
        ]

        for s in samples:
            p = Package(
                route_id=route.id,
                tracking_code=s["tracking_code"],
                address=s["address"],
                neighborhood=s["neighborhood"],
                latitude=s["latitude"],
                longitude=s["longitude"],
                status="pending",
                raw_data=s,
            )
            db.add(p)

        db.commit()
        print("Seed completed. Route ID:", route.id)
    finally:
        db.close()


if __name__ == "__main__":
    run()
