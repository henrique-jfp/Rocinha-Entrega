import os
from dotenv import load_dotenv
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from database import SessionLocal, get_db_session, Package, Route, init_db, LinkToken
import secrets


class PackageOut(BaseModel):
    id: int
    tracking_code: str
    address: Optional[str]
    neighborhood: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    # phone: Optional[str]  # DESABILITADO - precisa migração do banco
    status: str

    model_config = ConfigDict(from_attributes=True)


# in-memory location store for MVP
_latest_locations: dict[int, dict] = {}


def create_app() -> FastAPI:
    load_dotenv()
    init_db()

    app = FastAPI(title="Delivery System API")

    # Static and templates
    base_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(base_dir, "static")
    templates_dir = os.path.join(base_dir, "templates")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=templates_dir)

    BOT_USERNAME = os.getenv("BOT_USERNAME", "SEU_BOT_USERNAME")

    # Routes
    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/route/{route_id}/packages", response_model=List[PackageOut])
    def get_route_packages(route_id: int, db=Depends(get_db_session)):
        print(f"🔍 GET /route/{route_id}/packages - Buscando pacotes...")
        
        route = db.query(Route).filter(Route.id == route_id).first()
        if not route:
            print(f"❌ Rota {route_id} não encontrada!")
            raise HTTPException(status_code=404, detail="Route not found")
        
        print(f"✅ Rota encontrada: {route.name}")
        
        # Tenta ordenar por order_in_route, mas fallback para id se coluna não existir
        try:
            packages = (
                db.query(Package)
                .filter(Package.route_id == route_id)
                .order_by(Package.order_in_route.asc(), Package.id.asc())
                .all()
            )
            print(f"✅ Usando ordenação por order_in_route")
        except Exception as e:
            print(f"⚠️ order_in_route não existe, usando fallback: {e}")
            # Fallback se order_in_route não existir no banco
            packages = (
                db.query(Package)
                .filter(Package.route_id == route_id)
                .order_by(Package.id.asc())
                .all()
            )
        
        print(f"📦 {len(packages)} pacotes encontrados")
        for p in packages[:3]:  # Mostra os 3 primeiros
            print(f"  - {p.tracking_code}: lat={p.latitude}, lng={p.longitude}, status={p.status}")
        
        result = [PackageOut.model_validate(p) for p in packages]
        print(f"✅ Retornando {len(result)} pacotes serializados")
        return result

    @app.get("/map/{route_id}/{driver_id}", response_class=HTMLResponse)
    def map_page(route_id: int, driver_id: int, request: Request):
        # Force HTTPS for base_url to avoid mixed content errors
        base_url = str(request.base_url).rstrip("/")
        if base_url.startswith("http://") and "render.com" in base_url:
            base_url = base_url.replace("http://", "https://")
        
        return templates.TemplateResponse(
            "map.html",
            {
                "request": request,
                "route_id": route_id,
                "driver_id": driver_id,
                "bot_username": BOT_USERNAME,
                "base_url": base_url
            },
        )

    class LocationIn(BaseModel):
        latitude: float
        longitude: float
        timestamp: Optional[float] = None
        route_id: Optional[int] = None

    @app.post("/location/{driver_id}")
    def update_location(driver_id: int, loc: LocationIn):
        _latest_locations[driver_id] = {
            "driver_id": driver_id,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "timestamp": loc.timestamp,
            "route_id": loc.route_id,
        }
        return {"ok": True}

    @app.get("/location/{driver_id}")
    def get_location(driver_id: int):
        data = _latest_locations.get(driver_id)
        if not data:
            raise HTTPException(status_code=404, detail="No location yet")
        return data

    class GroupTokenIn(BaseModel):
        package_ids: List[int]

    class GroupTokenOut(BaseModel):
        token: str

    @app.post("/group-token", response_model=GroupTokenOut)
    def create_group_token(body: GroupTokenIn, db=Depends(get_db_session)):
        ids = [int(i) for i in body.package_ids if isinstance(i, (int, str))]
        if not ids:
            raise HTTPException(status_code=400, detail="package_ids vazio")
        # Limite de payload, armazenado no DB, token curto
        token = secrets.token_urlsafe(10)  # ~14 chars
        rec = LinkToken(token=token, type="deliver_group", data={"ids": ids})
        db.add(rec)
        db.commit()  # IMPORTANTE: Commit para salvar no banco!
        db.refresh(rec)  # Refresh para garantir que está salvo
        print(f"✅ Token criado e salvo: {token} para IDs {ids}")
        return {"token": token}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
