import os
from dotenv import load_dotenv
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from database import SessionLocal, get_db_session, Package, Route, init_db


class PackageOut(BaseModel):
    id: int
    tracking_code: str
    address: Optional[str]
    neighborhood: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
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
        route = db.query(Route).filter(Route.id == route_id).first()
        if not route:
            raise HTTPException(status_code=404, detail="Route not found")
        packages = (
            db.query(Package)
            .filter(Package.route_id == route_id)
            .order_by(Package.id.asc())
            .all()
        )
        return [PackageOut.model_validate(p) for p in packages]

    @app.get("/map/{route_id}/{driver_id}", response_class=HTMLResponse)
    def map_page(route_id: int, driver_id: int, request: Request):
        return templates.TemplateResponse(
            "map.html",
            {
                "request": request,
                "route_id": route_id,
                "driver_id": driver_id,
                "bot_username": BOT_USERNAME,
                "base_url": str(request.base_url).rstrip("/")
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

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
