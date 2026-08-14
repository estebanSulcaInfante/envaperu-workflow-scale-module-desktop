"""Render entrypoint for the isolated public edge-station demo."""

import os
from pathlib import Path

from app import create_app
from app.services.portfolio_demo_service import (
    PortfolioDemoPrelabelService,
    PortfolioDemoWeighingService,
)


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
STATIC_DIR = PROJECT_DIR / "frontend" / "dist"
DATABASE_PATH = Path(
    os.getenv("STATION_DATABASE_PATH", "/tmp/envaperu_edge_demo.db")
).expanduser()
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

app = create_app(
    config_overrides={
        "DEBUG": False,
        "USE_RELOADER": False,
        "SECRET_KEY": os.getenv("SECRET_KEY", "portfolio-edge-demo-only"),
        "RUNTIME_PROFILE": "PORTFOLIO_DEMO",
        "RUNTIME_SERVER": "waitress",
        "PORTFOLIO_DEMO_MODE": True,
        "SAME_ORIGIN_ONLY": True,
        "SYNC_ENABLED": False,
        "MONITORING_ENABLED": False,
        "ALLOW_SCALE_SIMULATION": True,
        "ALLOW_LOCAL_SCM_DEMO": True,
        "SIMULATE_PRINTER": True,
        "STATION_ID": "PESAJE-PORTFOLIO-DEMO",
        "STATION_CODE": "PESAJE-PORTFOLIO-DEMO",
        "STATION_UUID": "00000000-0000-4000-8000-000000000501",
        "SCM_OPERATOR_ID": "1",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{DATABASE_PATH.as_posix()}",
        "STATION_DATABASE_PATH": str(DATABASE_PATH),
        "STATION_BACKUP_DIR": os.getenv(
            "STATION_BACKUP_DIR", "/tmp/envaperu-edge-backups"
        ),
        "SCM_PRELABEL_SERVICE": PortfolioDemoPrelabelService(),
        "SCM_WEIGHING_SERVICE": PortfolioDemoWeighingService(),
    },
    static_dir=STATIC_DIR,
    start_workers=False,
)
