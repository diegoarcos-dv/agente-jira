# Despliegue Linux del módulo de voz

## Compatibilidad

El flujo de voz no necesita micrófono ni altavoces físicos en el servidor. El navegador captura
y reproduce; Linux sólo recibe el archivo, ejecuta Whisper/Gemma/Piper y devuelve JSON + WAV.

| Componente | Linux |
|---|---|
| Captura `MediaRecorder` | Se ejecuta en el navegador |
| Whisper `tiny` | `faster-whisper`, CPU/int8 explícito |
| Gemma | Ollama local en `127.0.0.1:11434` |
| Contexto | SQLite |
| TTS | Piper + ONNX Runtime, CPU, offline |
| Reproducción | Se ejecuta en el navegador |

SAPI5 y `pywin32` son sólo una alternativa de desarrollo en Windows. La dependencia `pywin32`
está condicionada a `sys_platform == "win32"`, por lo que no se instala en Linux.

## Requisito crítico del navegador

Fuera de `localhost`, `navigator.mediaDevices.getUserMedia()` requiere un contexto seguro. El
sitio debe publicarse mediante **HTTPS**. FastAPI puede permanecer en `127.0.0.1:8000` detrás de
Nginx, Caddy o el balanceador TLS de la infraestructura. Exponer sólo HTTP por la IP del servidor
hará que el botón no pueda abrir el micrófono aunque Whisper y Piper estén correctos.

## Preparación

Ejemplo para una distribución Debian/Ubuntu con Python 3.11 o superior:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build
cd ..

bash scripts/setup-piper-voice.sh
ollama pull gemma3:1b
```

`setup-piper-voice.sh` descarga una vez `es_MX-ald-medium.onnx` y su configuración al directorio
ignorado `backend/data/voices/`. Revise el `MODEL_CARD` de cualquier voz alternativa antes de
usarla. Después de la instalación, Piper no necesita Internet.

## Arranque

Para una prueba directa en la red interna:

```bash
AGENTE_JIRA_HOST=0.0.0.0 bash scripts/start-objective-4e.sh
```

Para producción, conserve el valor seguro predeterminado `127.0.0.1` y publique mediante proxy
HTTPS. Variables relevantes:

```bash
export VOICE_TTS_PROVIDER=piper
export VOICE_TTS_VOICE=es_MX-ald-medium
export VOICE_TTS_MODEL_PATH=/ruta/agente_jira/backend/data/voices/es_MX-ald-medium.onnx
export VOICE_TTS_LENGTH_SCALE=1.0
export VOICE_WHISPER_DEVICE=cpu
export VOICE_WHISPER_COMPUTE_TYPE=int8
export VOICE_WHISPER_HOTWORDS="Vic Jira tarea Task Story Bug Epic Subtask Héctor prioridad responsable envíala"
bash scripts/start-objective-4e.sh
```

## OAuth de Atlassian en producción

No uses la URL local de desarrollo como callback cuando la aplicación esté publicada. Define
la URL pública antes de arrancar el backend y registra **la misma URL exacta** en la aplicación
OAuth de Atlassian (incluyendo `https`, dominio, ruta y sin una barra final):

```bash
export AGENTE_JIRA_PUBLIC_BASE_URL="https://jira.ejemplo.com"
export AGENTE_JIRA_ATLASSIAN_CALLBACK_URL="https://jira.ejemplo.com/api/integrations/atlassian/callback"
export AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS="true"
```

`AGENTE_JIRA_ATLASSIAN_CALLBACK_URL` tiene prioridad. `AGENTE_JIRA_PUBLIC_BASE_URL` evita que
el valor predeterminado de desarrollo (`http://localhost:8000/...`) se use por accidente. El
proxy debe reenviar `Host`, `X-Forwarded-Proto` y `X-Forwarded-For`; FastAPI puede seguir
escuchando sólo en `127.0.0.1:8000`.

`AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS=true` hace que una identidad Atlassian válida se registre
en el primer acceso. Si se deja en `false`, el callback puede terminar en `NO_ALLOWED_LOCAL_USER`
cuando la cuenta todavía no existe en `app_users`.

Antes de probar el login, comprueba el valor efectivo:

```bash
curl -s http://127.0.0.1:8000/api/health
```

Después inicia el flujo desde el dominio público. No abras el backend por IP ni alternes entre
el dominio público y `localhost`, porque la cookie de sesión y el estado OAuth pertenecen al
origen que inició el flujo.

El script no descarga nada al arrancar. Si falta el modelo, informa el problema y la aplicación
continúa con respuestas de texto.

## Proxy HTTPS

El proxy debe permitir WebM/Opus multipart, cuerpos de al menos 10 MB y respuestas que pueden
tardar hasta 60 segundos por la primera carga local. Un bloque Nginx orientativo es:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 11m;
    proxy_read_timeout 75s;
}
```

La gestión del certificado depende de la infraestructura. Compruebe en el navegador que la URL
es HTTPS y que el permiso de micrófono no está bloqueado por una política corporativa.

## Validación después de subir

```bash
curl http://127.0.0.1:8000/api/health
.venv/bin/python -m pytest backend/tests -q
```

Luego, desde la URL HTTPS:

1. iniciar sesión;
2. comprobar el selector “Respuestas habladas”;
3. decir “Crea una tarea para corregir el login”;
4. completar responsable y prioridad;
5. verificar que el navegador reproduce el WAV;
6. decir “Envíala a Jira” y comprobar `blocked`.

No abra Ollama a Internet. FastAPI es el único consumidor y debe alcanzarlo por loopback. El TTS
no crea procesos con texto generado ni reproduce audio en el servidor; usa la API Python tipada
de Piper y devuelve el WAV al cliente.
