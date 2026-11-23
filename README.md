# Bocina CoDi

**Un QR de CoDi que anuncia en voz alta cada pago recibido.** Como las bocinas de pago de las tiendas en India, pero sobre CoDi y sin hardware: cualquier celular o tablet se convierte en la bocina del mostrador.

> "Recibiste 85 pesos."

Construido sobre la API de [pey](https://docs.pey.mx) para el Hackatón México 2026.

## Pruébalo en vivo, con un pago real

Esto no es una simulación: está en producción y cobra con CoDi de verdad a través de pey.

1. Abre el **[demo completo](https://web-production-e9e63f91.up.railway.app/demo)** en tu computadora y toca la bocina una vez para activar el sonido.
2. Escanea el QR de la bocina con la app de tu banco, en la sección **CoDi**.
3. Paga cualquier monto, por ejemplo **$1**.
4. En segundos la bocina dice **"Recibiste un peso"** y el celular del dueño imprime el comprobante con tu banco y la clave de rastreo.

El pago es real y llega a la cuenta del proyecto. También puedes abrir por separado la [bocina 3D](https://web-production-e9e63f91.up.railway.app/) o la [app del dueño](https://web-production-e9e63f91.up.railway.app/app).

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
                 Bocina: "Recibiste 85 pesos"    App: comprobante y
                 + registro del pago             movimientos al instante
```

## Funcionalidades

**Mostrador**
- QR fijo (`amount: 0`, sin expiración): el cliente ingresa el monto al pagar.
- Anuncio por voz de cada pago, con fila: si llegan varios pagos a la vez se anuncian uno por uno, completos y en orden.
- Bocina 3D interactiva: botones de volumen y repetir el último pago (también con teclado: ↑ ↓ y U); el LED indica el estado.
- Registro en vivo de los pagos verificados por pey y de la conexión; avisa en voz si se pierde la conexión.

**App del dueño**
- Total del día y movimientos de los últimos 30 días, agrupados por día, en tiempo real.
- Botón "Cobrar": muestra el QR fijo y permite agregar un monto para generar un QR dinámico.
- Cobro al celular: con el monto y el número del cliente, pey le envía una solicitud CoDi a la app de su banco. Queda como pendiente con cuenta regresiva y se confirma al llegar el pago; si vence o falla, se puede reenviar o cobrar con QR el mismo monto. Si una misma venta se paga dos veces, se marca como pago duplicado.
- Comprobante de "Pago recibido" con el monto en letra en cuanto pey confirma el pago.
- Búsqueda de pagos y asistente por texto o voz en la misma barra: "¿Cuánto vendí hoy?", "Cóbrale 90 de dos tortas".
- Perfil con Mi QR para compartir como imagen o imprimir, cuenta de depósito y voz de la bocina.
- Ajustes avanzados protegidos con PIN.
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
    index.html       Mostrador: bocina 3D interactiva
    app.html         App del dueño
    demo.html        Demo: bocina y app lado a lado con el mismo pago
    soundbox-display.js  Modelo 3D de la bocina (three.js)
    pey-codi.svg     Logo pey · CoDi
    vendor/three/    three.js r170
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
| `DEPOSIT_ACCOUNT_LABEL` | No | Cómo se muestra en el perfil la cuenta donde cae el dinero, ej. `BBVA ···· 2702` |
| `PUSH_EXPIRATION` | No | Segundos que dura una solicitud de cobro al celular (mínimo 360; por defecto 900) |
| `FIXED_QR_ID` / `FIXED_QR_STRING` | No | Amarra el QR fijo a la cuenta; sobrevive reinicios y deploys |
| `ADMIN_PIN` | Recomendada | PIN para entrar a Ajustes avanzados |
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

- **Bocina física de bajo costo** (ESP32 + bocina + WiFi) conectada al mismo flujo de eventos.
- **Enlace de pago** para compartir por WhatsApp, como respaldo cuando el cliente no tiene CoDi ligado a su número.
- **Ajustes de la bocina desde la app:** voz y volumen guardados en el servidor, para controlar la bocina del mostrador desde el celular.
- **Varios negocios:** alta con nombre y cuenta propios, en lugar de un solo negocio configurado por variables de entorno.
