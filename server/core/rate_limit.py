"""
server/core/rate_limit.py
==========================
Rate limiting para endpoints críticos.

Protege /scan de saturación: con 10 PCs enviando a 1 frame/seg cada una
= 10 req/seg al reconocedor. Sin límite, un cliente bugueado puede enviar
100 req/seg y colapsar el servidor.

Uso en endpoints:
    from server.core.rate_limit import limiter
    from slowapi.errors import RateLimitExceeded

    @router.post("/scan")
    @limiter.limit("30/minute")  # máx 30 scans por minuto por IP
    def procesar_scan(request: Request, ...):
        ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# El limiter usa la IP remota como clave de identificación
limiter = Limiter(key_func=get_remote_address)