import logging
import os
from pathlib import Path
from octocoupon.config import settings

log_dir = Path(settings.db_path).expanduser().parent
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "octocoupon.log"),
    ],
)

logger = logging.getLogger("octocoupon")
