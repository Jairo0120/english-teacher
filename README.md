# english-teacher

Tutor de inglés 100 % local por voz: **Whisper** (voz → texto) → **Ollama** (corrección y respuesta) → **Kokoro** (texto → voz).

## Requisitos
- Ollama con el modelo: `ollama pull gemma3:12b`
- `espeak-ng` (lo usa Kokoro)
- Modelos de voz descargados una vez: `uv run scripts/download_models.py`

Después de la descarga todo funciona sin conexión.

## Uso
```sh
uv run english-teacher                   # menú para elegir la práctica
uv run english-teacher conversation      # conversación libre
uv run english-teacher phrasal-verbs     # práctica de phrasal verbs
uv run english-teacher --say-natural     # dice también la versión correcta en voz alta
uv run english-teacher --level C1       # cambia el nivel (se guarda como predeterminado)
uv run english-teacher -m qwen3:14b -w medium -s 0.9
```
En la sesión: **Enter** para hablar y Enter para terminar, **escribe** una frase para enviarla como texto, **r** repite la última respuesta, **q** sale.
Cada sesión se guarda en `sessions/` como Markdown.

## Niveles
El nivel (por defecto **B2**) cambia cómo habla el tutor, cómo conversa, qué phrasal verbs usa y lo exigente que es. Se define en `src/english_teacher/levels.py` y se inserta en los prompts mediante marcadores `{{...}}`.

| | B1 | B2 | C1 |
|---|---|---|---|
| Inglés del tutor | Sencillo, sin idioms | Natural, con idioms y collocations | Nativo culto, con matices |
| Conversación | 1-2 frases, pregunta sencilla | Preguntas abiertas (opiniones, hipótesis); te pide desarrollar las respuestas cortas; sugiere versiones más ricas | Además te lleva la contraria y señala vocabulario repetido y registro |
| Phrasal verbs | Lista común (88) | Común + avanzada (165) | Avanzada (77) |
| Evaluación | Significado correcto | Significado correcto **y** uso natural | Igual que B2 |
| Velocidad de voz | 0.9 | 1.0 | 1.1 |

## Fluidez
Cuando hablas (no cuando escribes), cada respuesta muestra:
- **ppm**: palabras por minuto, desde que empiezas a hablar hasta que terminas (incluye pausas). Referencia: ~150 ppm en conversación nativa.
- **Pausas largas**: silencios de 0.7 s o más dentro de la respuesta, y la más larga.
- **% del tiempo hablando**.

Las pausas se detectan con el VAD (Silero) sobre el audio, porque Whisper estira las palabras y esconde los silencios. Al salir ves la media de la sesión comparada con tus últimas 5 sesiones. Todo se guarda en `progress/fluency.csv`.

## Prácticas
| Práctica | Cómo funciona |
|---|---|
| `conversation` | Charla libre. El tutor corrige cada frase (gramática y naturalidad) y sigue la conversación. |
| `phrasal-verbs` | El tutor explica un phrasal verb en inglés con un ejemplo y tú creas una frase. Tienes 2 intentos; si fallas, te da un ejemplo y pasa al siguiente. Prioriza los verbos que no has visto o que más te cuestan (progreso en `progress/phrasal_verbs.json`, lista en `data/phrasal_verbs.txt`). |

Para añadir una práctica nueva: crea una subclase de `Practice` en `src/english_teacher/practices.py`, su prompt en `prompts/` y regístrala en `PRACTICES`. Si la práctica tiene que evaluar algo (correcto / incorrecto), usa el modo evaluado como `PhrasalVerbs`: una llamada con salida JSON evalúa y otra genera lo que dice el tutor. Con modelos de ~12B es mucho más fiable que pedir las dos cosas en una sola respuesta.

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
