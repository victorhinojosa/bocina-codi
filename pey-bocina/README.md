# Bocina CoDi 🔊

Punto de venta con CoDi (vía [pey](https://docs.pey.mx)) que **anuncia en voz alta cada pago confirmado**:
"Recibiste cien pesos".

La confirmación **solo** sale de un webhook de pey con firma válida (Standard Webhooks), no de una
captura de pantalla ni de nada que mande el navegador.

```
Tendero teclea o dice "cóbrale 85" → POST /api/charges → pey POST /codi/qr → QR en pantalla
Cliente paga en su app bancaria → pey → POST /webhooks/pey (firma verificada + idempotencia)
→ SSE → la pantalla se pone verde y la bocina dice "Recibiste ochenta y cinco pesos"
```

## Correr en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # pon tu PEY_API_KEY (y lo demás si lo tienes)
uvicorn app.main:app --reload --port 8000
```

## Conectar el webhook (lo más importante)

pey no puede llegar a `localhost`; necesitas una URL pública:

```bash
cloudflared tunnel --url http://localhost:8000     # o: ngrok http 8000
```

1. Abre la app **desde la URL pública** (ej. `https://xxxx.trycloudflare.com`). En ⚙︎ Config aparece
   la URL del webhook ya armada: `https://xxxx.trycloudflare.com/webhooks/pey`.
2. En [portal.mipey.mx](https://portal.mipey.mx) → Desarrollador → ⚙︎ de tu API key → pega la URL → **Crear Webhook**.
3. Copia el secreto (`whsec_...`) a `PEY_WEBHOOK_SECRET` en `.env` y reinicia el servidor.
4. Genera un cobro de **$0.01**, págalo desde tu app bancaria y escucha la bocina.
5. Si no suena: portal → ⚙︎ → **Webhook Logs** muestra cada intento y la respuesta de tu servidor.

> Cada API key admite un solo webhook. Si cambias la URL del túnel, actualízala en el portal.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/charges` | Crea el QR en pey y devuelve el SVG |
| GET | `/api/charges` | Historial y total verificado del día |
| POST | `/webhooks/pey` | Recibe pagos de pey (firma + idempotencia por `webhook-id`) |
| GET | `/api/events` | SSE: avisos de pago en vivo para todas las pantallas abiertas |
| POST | `/api/tts` | Voz con ElevenLabs (la llave no sale del servidor) |
| POST | `/api/parse` | "cóbrale dos tortas de 45" → `{amount: 90, concept: "2 tortas"}` con Claude |
| POST | `/api/dev/simulate/{id}` | Solo con `ALLOW_SIMULATION=true`; se anuncia como "Simulación" |

## Notas

- El `id` que devuelve pey es el IDC de Banxico y llega como `codiQrId` en el webhook; así se liga cada pago con su cobro.
- Si el monto pagado no coincide con el cobrado, la pantalla lo marca en rojo.
- Abre la misma URL en otro celular: también suena. Ese es el modo "bocina" sin hardware.
- Sin ElevenLabs usa la voz del navegador; sin Claude, el dictado usa una regex para encontrar el número.
- Deploy (Railway/Render/Fly): comando `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. SQLite se borra en cada deploy; para el demo está bien.
