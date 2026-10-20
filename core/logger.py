"""项目统一日志。"""

from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger: logging.Logger = logging.getLogger("corvex2api")
