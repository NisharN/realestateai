# Piper runbook — self-hosted TTS

Voice replies are synthesised by Piper (offline, CPU) inside the backend
container. If Piper or a voice model is missing, `VoiceService.text_to_speech`
returns `None` and the browser's `speechSynthesis` speaks the reply instead —
the conversation never stalls on TTS.

## What the image ships

`backend/Dockerfile` installs the `piper` binary (v1.2.0, amd64) and downloads
the English voice `en_US-lessac-medium` into `/app/models/piper`. Arabic is
**not** downloaded at build time (the `ar_JO-kareem-medium` voice is ~60 MB and
the download must be checked against the licence for your deployment).

Settings (`backend/app/config.py`):

| Setting            | Default                | Meaning                                 |
|--------------------|------------------------|-----------------------------------------|
| `PIPER_MODEL_PATH` | `./models/piper`       | Directory holding `<voice>.onnx(.json)` |
| `PIPER_VOICE_EN`   | `en_US-lessac-medium`  | English voice                           |
| `PIPER_VOICE_AR`   | `ar_JO-kareem-medium`  | Arabic voice                            |
| `TTS_TIMEOUT_S`    | `2.0`                  | Hard cap per utterance, then `None`     |
| `FAULT_TTS`        | `false`                | Drill flag: force the browser fallback  |

## Add the Arabic voice

```bash
cd backend/models/piper
base=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium
curl -L -o ar_JO-kareem-medium.onnx      $base/ar_JO-kareem-medium.onnx
curl -L -o ar_JO-kareem-medium.onnx.json $base/ar_JO-kareem-medium.onnx.json
```

`docker-compose.yml` mounts `./backend/models` into the container, so no
rebuild is needed. Restart `backend` and check the logs for
`Piper TTS failed` warnings.

## Verify

```bash
docker compose exec backend sh -c 'echo "مرحبا، كيف أساعدك؟" | piper --model /app/models/piper/ar_JO-kareem-medium.onnx --output_file /tmp/ar.wav && ls -la /tmp/ar.wav'
docker compose exec backend sh -c 'echo "Hello from the Dubai property assistant" | piper --model /app/models/piper/en_US-lessac-medium.onnx --output_file /tmp/en.wav && ls -la /tmp/en.wav'
```

In the voice UI, the `audio` frame on a turn indicates Piper produced WAV; a
`speak` frame (text only) indicates the browser fallback was used.

## Latency

Medium voices synthesise ~1 s of audio in ~0.2 s on 2 vCPU. If replies are
routinely cut by `TTS_TIMEOUT_S`, switch to the `low` variant of the voice or
raise the timeout — the reply text is already on screen before audio arrives, so
a slower engine degrades to "text first, audio after", not to silence.

## Drills

Set `FAULT_TTS=true` on the backend service and confirm the voice UI still
speaks every reply through the browser. Unset afterwards.
