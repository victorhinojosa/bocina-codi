# Bocina CoDi

**Cobra con CoDi y escucha cada pago.** El cliente escanea el QR del mostrador, paga desde la app de su banco y, en cuanto pey confirma el dinero, la bocina lo dice en voz alta:

> "Recibiste 85 pesos."

Sin terminal, sin capturas de pantalla que revisar y sin instalar nada para el cliente. Y para el dueño, una app en el celular para ver cada pago al instante y cobrar a distancia.

![Demo: un pago real con CoDi; la bocina lo anuncia y la app del dueño lo muestra al instante](docs/demo.gif)

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

Son las dos de la tarde en una tiendita y hay fila. Un cliente paga con transferencia y le enseña su celular a Doña Mari: "ya quedó". Ella no tiene tiempo de abrir la app de su banco, así que confía en la captura de pantalla. Las capturas se pueden falsificar, y por eso muchos negocios todavía prefieren el efectivo.

CoDi existe desde 2019: transferencias inmediatas, sin terminal y sin comisión por tarjeta. Lo que le falta en el mostrador es responder, sin mirar ninguna pantalla, la única pregunta que importa: **¿de verdad me pagaron?**

## La solución: escucharlo

| Para el cliente | Para el tendero | Para el dueño |
|---|---|---|
| Escanea el QR con la app de su banco, pone el monto y paga. Nada que instalar. | Escucha "Recibiste 85 pesos" y sigue atendiendo. Nada que revisar. | Ve cada pago al instante en su celular, con el banco de quien pagó, y cobra a distancia. |

- **La bocina (`/`)**: lleva el QR fijo del negocio y anuncia cada pago en voz alta, uno por uno y en orden aunque lleguen varios a la vez. En el demo es un modelo 3D interactivo; en el roadmap, un aparato de bajo costo.
- **La app del dueño (`/app`)**: los pagos del día y del historial, cobros con monto exacto, cobro directo al celular del cliente y un asistente al que se le pregunta "¿cuánto vendí hoy?".

**La confirmación nunca viene del cliente.** Un pago solo se anuncia cuando pey lo confirma: por el aviso con firma verificada ([Standard Webhooks](https://www.standardwebhooks.com/)) o, si ese aviso se pierde, consultando directamente la API de pey. Una captura de pantalla no hace sonar la bocina.

**Respaldo del webhook.** Mientras haya una pantalla conectada, el servidor consulta a pey cada 45 s (y en cuanto una pantalla se reconecta) los pagos del QR fijo, de los QR con monto y de los cobros al celular pendientes. El `transactionId` es la clave: un pago nunca se guarda ni se anuncia dos veces, llegue primero por el webhook o por el respaldo. Solo se anuncian en voz los pagos de los últimos 2 minutos; los más viejos entran al historial marcados como *Recuperado*. Cada pago guarda `paid_at` (cuándo pagó, según pey), `received_at` (cuándo llegó el webhook) y `created_at` (cuándo lo registró la app).

## Cómo funciona

```
Cliente escanea el QR (o acepta el cobro en su celular) ──► paga desde su app bancaria (CoDi)
                                         │
                                         ▼
                       pey ──► POST /webhooks/pey
                                 ├─ verifica la firma
                                 ├─ descarta duplicados (webhook-id / transactionId)
                                 └─ guarda el pago
                       respaldo: si el webhook no llega, el servidor consulta
                       GET /transaction/codi/qr/{id} cada 45 s y al reconectar
                                         │
                                  Server-Sent Events
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                 Bocina: "Recibiste 85 pesos"    App: comprobante y
                 + registro del pago             movimientos al instante
```

## Funcionalidades

**Bocina (mostrador)**
- QR fijo (`amount: 0`, sin expiración): el cliente ingresa el monto al pagar.
- Anuncio por voz de cada pago, con fila: si llegan varios pagos a la vez se anuncian uno por uno, completos y en orden.
- Bocina 3D interactiva: botones de volumen y repetir el último pago (también con teclado: ↑ ↓ y U); el LED indica el estado.
- Registro en vivo de los pagos verificados por pey y de la conexión; avisa en voz si se pierde la conexión.

**App del dueño**
- Total de hoy (y de ayer) y movimientos de los últimos 30 días agrupados por día, en tiempo real.
- Cada movimiento muestra el banco y los últimos 4 dígitos de la cuenta de quien pagó.
- Botón "Cobrar": muestra el QR fijo y permite agregar un monto para generar un QR con monto exacto.
- Cobro al celular: con el monto y el número del cliente, pey le envía el cobro CoDi a la app de su banco. Queda como pendiente con cuenta regresiva y se confirma al llegar el pago; si vence o falla, se puede reenviar o generar un QR con el mismo monto. Si una misma venta se paga dos veces, se marca como pago duplicado.
- Comprobante de "Pago recibido" con el monto en letra, el banco de origen y la clave de rastreo.
- Búsqueda de pagos y asistente por texto o voz en la misma barra: "¿Cuánto vendí hoy?", "Cóbrale 90 de dos tortas".
- Perfil con Mi QR para compartir como imagen, cuenta de depósito y ajustes de sonido.
- Ajustes avanzados protegidos con PIN, con el estado del servidor (incluye si el historial está en almacenamiento persistente).
- Instalable como app (PWA).

**Demo (`/demo`)**
- La bocina y la app del dueño lado a lado, reaccionando al mismo pago.

## Stack

- **Backend:** Python, FastAPI, SQLite, Server-Sent Events.
- **Pagos:** API de pey (CoDi), webhooks firmados con Standard Webhooks.
- **Voz:** ElevenLabs (texto a voz) con respaldo en la voz del navegador; Web Speech API para dictado.
- **Asistente:** LLM vía API de Anthropic (opcional; sin llave funciona con reglas simples).
- **Frontend:** HTML, CSS y JavaScript sin frameworks.

## Estructura

```
app/
  main.py            Arma la app: rutas, arranque y respaldo en segundo plano
  config.py          Variables de entorno
  db.py              Tablas SQLite y migraciones
  timeutil.py        Horas en la zona del negocio (BUSINESS_TZ) y horas habladas
  speech.py          Montos en letra y frases para la voz
  pey.py             Cliente de la API de pey
  payments.py        Registrar un pago (una sola vez), anunciarlo e historial
  recovery.py        Respaldo del webhook: recupera pagos consultando a pey
  events.py          Eventos en vivo (SSE)
  routes/            Endpoints: cobros, historial, webhook, voz, páginas, estado
  static/
    index.html       Mostrador: bocina 3D interactiva
    app.html         App del dueño
    demo.html        Demo: bocina y app lado a lado con el mismo pago
    soundbox-display.js  Modelo 3D de la bocina (three.js)
    pey-codi.svg     Logo pey · CoDi
    vendor/three/    three.js r170
    common.js        Fila de voz, eventos en vivo y utilidades compartidas
    icon.svg
docs/demo.gif        GIF del demo para este README
tests/               Pruebas (pytest)
requirements.txt
requirements-dev.txt Dependencias para las pruebas
Procfile             Comando de arranque
railway.json         Configuración de despliegue en Railway
.env.example         Variables de entorno
```

## Correr en local

Requisitos: Python 3.12+ y una cuenta en [pey](https://portal.pey.mx).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # agrega tu PEY_API_KEY
uvicorn app.main:app --reload --port 8000
```

- Bocina: http://localhost:8000
- App del dueño: http://localhost:8000/app
- Demo: http://localhost:8000/demo

### Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Cubren firma inválida, webhooks duplicados, monto incorrecto, dos pagos de la misma venta, webhook que llega después de recuperar el pago, el respaldo al reconectar y las horas en la zona del negocio. No llaman a pey ni usan las llaves del `.env`.

### Conectar el webhook

pey necesita una URL pública para avisar de los pagos. En local puedes usar un túnel:

```bash
ngrok http 8000        # o: cloudflared tunnel --url http://localhost:8000
```

1. En [portal.pey.mx](https://portal.pey.mx) → **Desarrollador** → ⚙︎ de tu API key, registra `https://<tu-url>/webhooks/pey`.
2. Copia el secreto (`whsec_...`) en `PEY_WEBHOOK_SECRET` y reinicia el servidor.
3. Haz un pago de prueba. Si no llega, revisa los **Logs de Webhook** del portal.

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
| `BUSINESS_TZ` | No | Zona horaria del negocio para decir las horas y calcular "hoy" (por defecto `America/Mexico_City`) |
| `RECOVERY_POLL_SECONDS` | No | Cada cuántos segundos el respaldo consulta a pey si hay pantallas conectadas (por defecto 45; 0 = apagado) |
| `ANNOUNCE_WINDOW_SECONDS` | No | Solo se anuncian en voz los pagos de los últimos N segundos (por defecto 120) |
| `DB_PATH` | No | Ruta de la base SQLite (en Railway: `/data/bocina.db`) |
| `ALLOW_SIMULATION` | No | Permite simular pagos para pruebas; dejar en `false` en producción |

## Despliegue

El servidor necesita un proceso siempre activo (para los eventos en vivo) y un disco persistente (para SQLite), por lo que se despliega en [Railway](https://railway.com) en lugar de una plataforma serverless.

1. **New Project → Deploy from GitHub repo** y selecciona este repositorio. El comando de arranque se toma de `railway.json`.
2. En el servicio, agrega un **Volume** montado en `/data` (sin volumen, el historial se borra en cada despliegue; la app lo avisa en Ajustes avanzados).
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
| `POST` | `/api/push` | Envía un cobro CoDi al celular del cliente |
| `POST` | `/api/push/{id}/dismiss` | Quita de la lista un cobro al celular pendiente |
| `GET` | `/api/payments` | Pagos, cobros al celular pendientes y totales de hoy y ayer |
| `GET` | `/api/last-payment` | Último pago, con la frase para anunciarlo |
| `POST` | `/api/assistant` | Asistente: responde sobre las ventas o genera un cobro |
| `POST` | `/api/tts` | Texto a voz |
| `GET` | `/api/status` | Estado de la configuración |

## Roadmap

- **Bocina física de bajo costo** (ESP32 + bocina + WiFi) conectada al mismo flujo de eventos.
- **Enlace de pago** para compartir por WhatsApp, como respaldo cuando el cliente no tiene CoDi ligado a su número.
- **Ajustes de la bocina desde la app:** voz y volumen guardados en el servidor, para controlar la bocina del mostrador desde el celular.
- **Varios negocios:** alta con nombre y cuenta propios, en lugar de un solo negocio configurado por variables de entorno.
