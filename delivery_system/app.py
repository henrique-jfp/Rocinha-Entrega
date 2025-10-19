import os
from datetime import datetime
from dotenv import load_dotenv
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from database import get_db_session, Package, Route, init_db, LinkToken
import secrets

# Logging estruturado e validadores
from shared.logger import logger, log_api_request
from shared.validators import validate_coordinates, log_validation_error


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
    
    # ═══════════════════════════════════════════════════════════
    # CORS - Configuração de Segurança
    # ═══════════════════════════════════════════════════════════
    # Permite apenas origens específicas (configuradas via .env)
    # Em desenvolvimento: http://localhost:8000
    # Em produção: domínios autorizados (Railway, frontend, etc)
    from fastapi.middleware.cors import CORSMiddleware
    
    ALLOWED_ORIGINS = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000"  # Padrão seguro para desenvolvimento
    ).split(",")
    
    # Remove espaços em branco das origens
    ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,  # ✅ Restrito a domínios específicos
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],  # Métodos HTTP específicos
        allow_headers=["Content-Type", "Authorization"],  # Headers específicos
    )

    # Static and templates
    base_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(base_dir, "static")
    templates_dir = os.path.join(base_dir, "templates")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=templates_dir)

    BOT_USERNAME = os.getenv("BOT_USERNAME", "SEU_BOT_USERNAME")

    # Routes
    @app.get("/health")
    def health(db=Depends(get_db_session)):
        """
        Healthcheck endpoint melhorado
        - Verifica conexão com banco de dados
        - Retorna informações úteis para monitoramento
        """
        import time
        from sqlalchemy import text
        
        start_time = time.time()
        health_data = {
            "status": "healthy",
            "timestamp": start_time,
            "checks": {}
        }
        
        # Verifica conexão com banco de dados
        try:
            # Query simples para testar conexão (timeout de 5s)
            db.execute(text("SELECT 1"))
            db_latency = round((time.time() - start_time) * 1000, 2)  # ms
            
            health_data["checks"]["database"] = {
                "status": "up",
                "latency_ms": db_latency
            }
            logger.debug(f"Healthcheck: Database OK ({db_latency}ms)")
            
        except Exception as e:
            health_data["status"] = "unhealthy"
            health_data["checks"]["database"] = {
                "status": "down",
                "error": str(e)
            }
            logger.error("Healthcheck: Database FALHOU", exc_info=True)
        
        # Verifica variáveis de ambiente críticas
        critical_env_vars = ["BOT_TOKEN", "DATABASE_URL"]
        missing_vars = [var for var in critical_env_vars if not os.getenv(var)]
        
        if missing_vars:
            health_data["status"] = "unhealthy"
            health_data["checks"]["environment"] = {
                "status": "incomplete",
                "missing": missing_vars
            }
            logger.warning(f"Healthcheck: Variáveis faltando: {missing_vars}")
        else:
            health_data["checks"]["environment"] = {"status": "ok"}
        
        # Define status HTTP apropriado
        status_code = 200 if health_data["status"] == "healthy" else 503
        
        from fastapi.responses import JSONResponse
        return JSONResponse(content=health_data, status_code=status_code)

    @app.get("/route/{route_id}/packages", response_model=List[PackageOut])
    def get_route_packages(route_id: int, db=Depends(get_db_session)):
        logger.info(f"GET /route/{route_id}/packages - Buscando pacotes")
        
        try:
            route = db.query(Route).filter(Route.id == route_id).first()
            if not route:
                logger.warning(f"Rota {route_id} não encontrada")
                raise HTTPException(status_code=404, detail="Route not found")
            
            logger.debug(f"Rota encontrada: {route.name}")
            
            # Tenta ordenar por order_in_route, mas fallback para id se coluna não existir
            try:
                packages = (
                    db.query(Package)
                    .filter(Package.route_id == route_id)
                    .order_by(Package.order_in_route.asc(), Package.id.asc())
                    .all()
                )
                logger.debug("Usando ordenação por order_in_route")
            except Exception as e:
                logger.warning(f"order_in_route não existe, usando fallback por ID")
                # Fallback se order_in_route não existir no banco
                packages = (
                    db.query(Package)
                    .filter(Package.route_id == route_id)
                    .order_by(Package.id.asc())
                    .all()
                )
            
            logger.info(f"{len(packages)} pacotes encontrados na rota {route_id}")
            if packages:
                logger.debug(f"Primeiros pacotes: {[p.tracking_code for p in packages[:3]]}")
            
            result = []
            for p in packages:
                try:
                    # Valida coordenadas do pacote antes de serializar
                    if p.latitude is not None or p.longitude is not None:
                        is_valid, error_msg = validate_coordinates(
                            p.latitude, 
                            p.longitude, 
                            strict=False  # Não obriga Brasil (pode ter coordenadas inválidas antigas)
                        )
                        
                        if not is_valid:
                            logger.warning(
                                f"Pacote {p.id} tem coordenadas inválidas: {error_msg}",
                                extra={
                                    "package_id": p.id,
                                    "tracking_code": p.tracking_code,
                                    "latitude": p.latitude,
                                    "longitude": p.longitude
                                }
                            )
                            # Define coordenadas como None se inválidas
                            # (permite mapa funcionar mesmo com dados ruins)
                            p.latitude = None
                            p.longitude = None
                    
                    item = PackageOut.model_validate(p)
                    result.append(item)
                except Exception as e:
                    logger.error(f"Erro ao serializar pacote {p.id}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Serialization error for package {p.id}: {str(e)}")
            
            logger.info(f"Retornando {len(result)} pacotes serializados para rota {route_id}")
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Erro geral em get_route_packages para rota {route_id}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Erro ao carregar pacotes: {str(e)}")

    @app.get("/map/{route_id}/{driver_id}", response_class=HTMLResponse)
    def map_page(route_id: int, driver_id: int, request: Request):
        # Force HTTPS for base_url to avoid mixed content errors
        base_url = str(request.base_url).rstrip("/")
        original_url = base_url
        
        # Headers úteis para debug
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        host_header = request.headers.get("Host", "")
        
        # Se está rodando em produção, sempre force HTTPS
        # Critérios: header X-Forwarded-Proto=https OU URL em produção (railway/render)
        is_production = (
            forwarded_proto == "https" or
            "railway.app" in base_url or
            "render.com" in base_url or
            "rocinha-entrega" in base_url
        )
        
        if is_production and base_url.startswith("http://"):
            base_url = base_url.replace("http://", "https://", 1)
        
        print(f"📱 Map page carregado:")
        print(f"   route_id={route_id}, driver_id={driver_id}")
        print(f"   URL original: {original_url}")
        print(f"   X-Forwarded-Proto: {forwarded_proto}")
        print(f"   X-Forwarded-Host: {forwarded_host}")
        print(f"   Host header: {host_header}")
        print(f"   É produção: {is_production}")
        print(f"   ✅ base_url final: {base_url}")
        
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
        """
        Atualiza localização do motorista
        Valida coordenadas antes de armazenar
        """
        # Valida coordenadas (strict=True para validar se está no Brasil)
        is_valid, error_msg = validate_coordinates(
            loc.latitude, 
            loc.longitude, 
            strict=True  # Requer coordenadas brasileiras
        )
        
        if not is_valid:
            log_validation_error("location", loc.model_dump(), error_msg)
            raise HTTPException(
                status_code=400, 
                detail=f"Coordenadas inválidas: {error_msg}"
            )
        
        _latest_locations[driver_id] = {
            "driver_id": driver_id,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "timestamp": loc.timestamp,
            "route_id": loc.route_id,
        }
        
        logger.debug(f"Localização atualizada para motorista {driver_id}: ({loc.latitude}, {loc.longitude})")
        return {"ok": True}

    @app.get("/location/{driver_id}")
    def get_location(driver_id: int):
        data = _latest_locations.get(driver_id)
        if not data:
            raise HTTPException(status_code=404, detail="No location yet")
        return data

    class MarkDeliveredIn(BaseModel):
        status: str = "delivered"

    @app.post("/package/{package_id}/mark-delivered")
    def mark_package_delivered(package_id: int, body: MarkDeliveredIn, db=Depends(get_db_session)):
        """Marca um pacote como entregue diretamente do mapa"""
        try:
            package = db.query(Package).filter(Package.id == package_id).first()
            if not package:
                raise HTTPException(status_code=404, detail=f"Pacote {package_id} não encontrado")
            
            route_id = package.route_id
            
            print(f"📦 Marcando pacote {package_id} como {body.status}...")
            
            # Atualiza status
            old_status = package.status
            package.status = body.status
            db.add(package)
            db.commit()
            db.refresh(package)

            # Após marcar entregue/falhado, verifica se a rota foi concluída (todos entregues)
            if route_id is not None and body.status == "delivered":
                try:
                    total = db.query(Package).filter(Package.route_id == route_id).count()
                    delivered = db.query(Package).filter(
                        Package.route_id == route_id,
                        Package.status == "delivered"
                    ).count()
                    # Marca rota como completed apenas se todos foram entregues e rota ainda não está finalizada
                    if total > 0 and delivered == total:
                        route = db.query(Route).filter(Route.id == route_id).first()
                        if route and route.status != "finalized":
                            route.status = "completed"
                            route.completed_at = route.completed_at or datetime.utcnow()
                            db.add(route)
                            db.commit()
                            print(f"✅ Rota {route_id} marcada como COMPLETED (todos os {total} pacotes entregues)")
                except Exception as e:
                    # Não falha o endpoint por erro nessa checagem; apenas loga
                    print(f"⚠️ Falha ao atualizar status da rota {route_id}: {e}")
            
            print(f"✅ Pacote {package_id}: {old_status} → {body.status}")
            
            return {
                "success": True,
                "package_id": package.id,
                "tracking_code": package.tracking_code,
                "old_status": old_status,
                "new_status": body.status,
                "message": f"Pacote {package.tracking_code} marcado como {body.status}"
            }
        
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Erro ao marcar pacote: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Erro ao atualizar pacote: {str(e)}")

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
