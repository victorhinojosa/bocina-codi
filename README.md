# Bocina CoDi

**Un QR de CoDi que anuncia en voz alta cada pago recibido.** Como las bocinas de pago de las tiendas en India, pero sobre CoDi y sin hardware: cualquier celular o tablet se convierte en la bocina del mostrador.

> "Recibiste 85 pesos."

Construido sobre la API de [pey](https://docs.pey.mx) para el Hackatón México 2026.

---

## El problema

CoDi permite cobrar con transferencias inmediatas y sin comisión desde 2019, pero en el mostrador sigue habiendo una pregunta sin resolver: **¿de verdad me pagaron?** Hoy el comerciante revisa la app de su banco o confía en una captura de pantalla que el cliente le muestra, y las capturas se pueden falsificar.

En India este problema lo resolvió una bocina junto al QR que anuncia cada pago. El comerciante no necesita mirar ninguna pantalla: lo escucha.

## La solución

Bocina CoDi tiene dos partes:

- **Mostrador (`/`)**: muestra el QR fijo del negocio. El cliente lo escanea con su app bancaria, pone el monto y paga. En cuanto pey confirma el pago, la pantalla se pone verde y la bocina dice el monto. Se puede preguntar por voz cuánto se ha vendido.
- **App del dueño (`/app`)**: pensada para el celular. Muestra las ventas del día en tiempo real, genera cobros con monto exacto (el QR aparece en el celular para que el cliente lo escanee) e incluye un asistente para consultar las ventas.

**La confirmación nunca viene del cliente.** Cada pago se anuncia solo después de recibir un webhook de pey con firma verificada ([Standard Webhooks](https://www.standardwebhooks.com/)).

## Cómo funciona

```
Cliente escanea el QR fijo ──► paga desde su app bancaria (CoDi / SPEI)
                                         │
                                         ▼
                       pey ──► POST /webhooks/pey
                                 ├─ verifica la firma
                                 ├─ descarta duplicados (webhook-id / transactionId)
                                 └─ guarda el pago
                                         │
                                  Server-Sent Events
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                 Mostrador: pantalla verde        App: el pago aparece
                 + "Recibiste 85 pesos"           en las ventas del día
```

## Funcionalidades

**Mostrador**
- QR fijo (`amount: 0`, sin expiración): el cliente ingresa el monto al pagar.
- Anuncio por voz de cada pago, con fila: si llegan varios pagos a la vez se anuncian uno por uno, completos y en orden.
- Botones de volumen, repetir el último pago y hablar con el asistente (también con teclado: ↑ ↓, U y espacio).
- Si el monto recibido no coincide con el cobrado, se marca en pantalla.

**App del dueño**
- Total y lista de pagos del día en tiempo real.
- Cobro con monto: genera un QR dinámico que se muestra en el celular y cambia a "Pagado" cuando llega la confirmación.
- Asistente por texto o voz: "¿Cuánto vendí hoy?", "Últimas 3 transacciones", "Cóbrale 90 de dos tortas".
- Ajustes protegidos con PIN.
- Instalable como app (PWA).

## Stack

- **Backend:** Python, FastAPI, SQLite, Server-Sent Events.
- **Pagos:** API de pey (CoDi), webhooks firmados con Standard Webhooks.
- **Voz:** ElevenLabs (texto a voz) con respaldo en la voz del navegador; Web Speech API para dictado.
- **Asistente:** LLM vía API de Anthropic (opcional; sin llave funciona con reglas simples).
- **Frontend:** HTML, CSS y JavaScript sin frameworks.

## Estructura

```
app/
  main.py            API, webhook de pey, SSE, voz y asistente
  static/
    index.html       Mostrador
    app.html         App del dueño
    common.js        Fila de voz, eventos en vivo y utilidades compartidas
    icon.svg
requirements.txt
Procfile             Comando de arranque
railway.json         Configuración de despliegue en Railway
.env.example         Variables de entorno
```

## Correr en local

Requisitos: Python 3.12+ y una cuenta en [pey](https://portal.mipey.mx).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # agrega tu PEY_API_KEY
uvicorn app.main:app --reload --port 8000
```

- Mostrador: http://localhost:8000
- App del dueño: http://localhost:8000/app

### Conectar el webhook

pey necesita una URL pública para avisar de los pagos. En local puedes usar un túnel:

```bash
ngrok http 8000        # o: cloudflared tunnel --url http://localhost:8000
```

1. En [portal.mipey.mx](https://portal.mipey.mx) → **Developer** → ⚙︎ de tu API key, registra `https://<tu-url>/webhooks/pey`.
2. Copia el secreto (`whsec_...`) en `PEY_WEBHOOK_SECRET` y reinicia el servidor.
3. Haz un pago de prueba. Si no llega, revisa los **Webhook Logs** del portal.

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `PEY_API_KEY` | Sí | API key de pey |
| `PEY_WEBHOOK_SECRET` | Sí | Secreto del webhook (`whsec_...`) |
| `BUSINESS_NAME` | No | Nombre que ve el cliente al pagar |
| `FIXED_QR_ID` / `FIXED_QR_STRING` | No | Amarra el QR fijo a la cuenta; sobrevive reinicios y deploys |
| `ADMIN_PIN` | Recomendada | PIN para entrar a Ajustes |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | No | Voz natural; sin llave se usa la voz del navegador |
| `ANTHROPIC_API_KEY` | No | Asistente con lenguaje natural; sin llave usa reglas |
| `DEFAULT_EXPIRATION` | No | Expiración de los QR con monto en segundos (0 = no expira; mínimo 360) |
| `DB_PATH` | No | Ruta de la base SQLite (en Railway: `/data/bocina.db`) |
| `ALLOW_SIMULATION` | No | Permite simular pagos para pruebas; dejar en `false` en producción |

## Despliegue

El servidor necesita un proceso siempre activo (para los eventos en vivo) y un disco persistente (para SQLite), por lo que se despliega en [Railway](https://railway.com) en lugar de una plataforma serverless.

1. **New Project → Deploy from GitHub repo** y selecciona este repositorio. El comando de arranque se toma de `railway.json`.
2. En el servicio, agrega un **Volume** montado en `/data`.
3. En **Variables**, pega el contenido de tu `.env` (Raw Editor) y define `DB_PATH=/data/bocina.db`.
4. En **Settings → Networking**, genera un dominio público.
5. Actualiza la URL del webhook en el portal de pey a `https://<tu-dominio>/webhooks/pey`.

## API

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/webhooks/pey` | Recibe pagos de pey (firma verificada e idempotencia) |
| `GET` | `/api/events` | Eventos en vivo (SSE) |
| `GET` | `/api/fixed-qr` | QR fijo activo |
| `POST` | `/api/fixed-qr` | Crea un QR fijo nuevo (requiere PIN) |
| `POST` | `/api/charges` | Crea un QR con monto |
| `GET` | `/api/payments` | Pagos y total verificado del día |
| `GET` | `/api/last-payment` | Último pago, con la frase para anunciarlo |
| `POST` | `/api/assistant` | Asistente: responde sobre las ventas o genera un cobro |
| `POST` | `/api/tts` | Texto a voz |
| `GET` | `/api/status` | Estado de la configuración |

## Roadmap

- **Cobro directo al celular:** enviar la solicitud de pago al número del cliente con la notificación push de CoDi, sin escanear.
- **Link de pago:** un QR que se abre con la cámara nativa del teléfono, para clientes sin CoDi activado.
- **Activación por voz** ("Oye pey") con detección de palabra clave en el dispositivo.
- **Bocina física de bajo costo** (ESP32 + bocina + WiFi) conectada al mismo flujo de eventos.
