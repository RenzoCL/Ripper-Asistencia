"""
server/services/notifications/whatsapp_service.py
==================================================
Servicio de notificaciones via WhatsApp Web + Selenium.

IMPORTANTE: Este servicio es OPCIONAL y más complejo de configurar.
Se recomienda usar Telegram primero. WhatsApp Web tiene limitaciones:
  - Requiere escanear un QR code una vez al iniciar (luego persiste la sesión).
  - WhatsApp puede detectar automatización y bloquear el número.
  - Más lento que Telegram (2–5 segundos por mensaje).
  - Requiere Chrome/Chromium instalado en el servidor.

Cuándo usar WhatsApp:
  - Cuando los apoderados NO tienen Telegram pero sí WhatsApp (mayoría).
  - Para colegios donde el 100% de comunicación familiar es por WhatsApp.

Configuración requerida en .env:
  WHATSAPP_ENABLED=true
  (El número origen es el que escanea el QR con WhatsApp Web)

Instalación adicional:
  pip install selenium webdriver-manager
  sudo apt-get install chromium-browser  # Linux
"""

import logging
import time
import os
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class WhatsAppService:
    """
    Envía mensajes de WhatsApp usando Selenium + WhatsApp Web.

    Flujo de sesión:
      1. Primera vez: abre navegador, muestra QR, espera escaneo (~30s).
      2. Guarda la sesión en ./server/data/whatsapp_session/.
      3. Reinicios posteriores: carga la sesión sin QR (si no expiró).
      4. La sesión expira si WhatsApp Web cierra sesión (raro, ~30 días).
    """

    SESSION_DIR = "./server/data/whatsapp_session"

    def __init__(self):
        self.driver = None
        self._conectado = False
        self._habilitado = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"

        if not self._habilitado:
            logger.info("WhatsApp deshabilitado (WHATSAPP_ENABLED=false en .env)")

    def inicializar(self) -> bool:
        """
        Inicia Selenium con Chrome y carga WhatsApp Web.
        Si hay sesión guardada, intenta usarla (sin QR).
        Retorna True si la conexión fue exitosa.
        """
        if not self._habilitado:
            return False

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from webdriver_manager.chrome import ChromeDriverManager

            # Configurar Chrome en modo sin interfaz gráfica (headless)
            # NOTA: WhatsApp Web NO funciona en modo headless real.
            # Usar modo "virtual display" con xvfb en Linux si es necesario.
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument(f"--user-data-dir={self.SESSION_DIR}")  # Persistir sesión
            options.add_argument("--window-size=1280,720")

            # En servidor Linux sin monitor, usar Xvfb:
            # Xvfb :99 -screen 0 1280x720x24 &
            # DISPLAY=:99 uvicorn server.main:app ...

            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.get("https://web.whatsapp.com")

            # Esperar hasta 60s a que cargue (con sesión previa salta el QR)
            wait = WebDriverWait(self.driver, 60)
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-icon="search"]')
            ))

            self._conectado = True
            logger.info("✅ WhatsApp Web conectado exitosamente")
            return True

        except ImportError:
            logger.error(
                "Selenium no instalado. Ejecutar: pip install selenium webdriver-manager"
            )
            return False
        except Exception as e:
            logger.error("Error conectando WhatsApp Web: %s", e)
            self._conectado = False
            return False

    def enviar_mensaje(self, numero: str, mensaje: str) -> bool:
        """
        Envía un mensaje de WhatsApp a un número específico.

        Args:
            numero: Número internacional SIN '+' ni espacios. Ej: '51987654321'
            mensaje: Texto del mensaje (solo texto plano, sin HTML)

        Returns:
            True si el mensaje se envió exitosamente.
        """
        if not self._habilitado or not self._conectado:
            return False

        if not self.driver:
            logger.warning("WhatsApp: driver no iniciado")
            return False

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            # URL directa al chat del número (evita buscar manualmente)
            url = f"https://web.whatsapp.com/send?phone={numero}&text={mensaje}"
            self.driver.get(url)

            # Esperar que cargue el campo de texto
            wait = WebDriverWait(self.driver, 20)
            caja_texto = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="conversation-compose-box-input"]')
            ))

            time.sleep(2)  # Pausa breve para asegurar carga completa
            caja_texto.send_keys(Keys.ENTER)  # Enviar el mensaje (ya está en la URL)

            time.sleep(1)  # Esperar confirmación visual
            logger.info("WhatsApp: Mensaje enviado a %s", numero[:5] + "***")
            return True

        except Exception as e:
            logger.error("Error enviando WhatsApp a %s: %s", numero[:5] + "***", e)
            return False

    def cerrar(self):
        """Cierra el navegador. Llamar al detener el servidor."""
        if self.driver:
            self.driver.quit()
            self._conectado = False
            logger.info("WhatsApp Web: Navegador cerrado")

    @property
    def habilitado(self) -> bool:
        return self._habilitado

    @property
    def conectado(self) -> bool:
        return self._conectado


# Instancia global
whatsapp_service = WhatsAppService()
