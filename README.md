# english-teacher

Tutor de inglés 100 % local por voz: **Whisper** (voz → texto) → **Ollama** (corrección y respuesta) → **Kokoro** (texto → voz).

## Requisitos
- Ollama con el modelo: `ollama pull gemma3:12b`
- `espeak-ng` (lo usa Kokoro)
- Modelos de voz descargados una vez: `uv run scripts/download_models.py`

Después de la descarga todo funciona sin conexión.

## Uso
```sh
uv run english-teacher                 # sesión de práctica
uv run english-teacher --say-natural   # dice también la versión correcta en voz alta
uv run english-teacher -m qwen3:14b -w medium -s 0.9
```
En la sesión: **Enter** para hablar y Enter para terminar, **escribe** una frase para enviarla como texto, **r** repite la última respuesta, **q** sale.
Cada sesión se guarda en `sessions/` como Markdown.

## Scripts
| Script | Para qué |
|---|---|
| `scripts/compare_models.py` | Comparar modelos de Ollama con frases con errores típicos |
| `scripts/try_stt.py` | Probar Whisper con tu voz y comparar tamaños |
| `scripts/try_tts.py` | Escuchar voces y velocidades de Kokoro |
| `scripts/download_models.py` | Descargar modelos de Whisper y Kokoro |

## Tests
```sh
uv run pytest
```
