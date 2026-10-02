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
uv run english-teacher tenses            # tiempos verbales
uv run english-teacher paraphrase        # escuchar un texto y contarlo con tus palabras
uv run english-teacher roleplay          # escena con un personaje
uv run english-teacher writing -f texto.txt   # revisión de un texto escrito (sin voz)
uv run english-teacher --say-natural     # dice también la versión correcta en voz alta
uv run english-teacher --level C1       # cambia el nivel (se guarda como predeterminado)
uv run english-teacher -m qwen3:14b -w medium -s 0.9
```
En la sesión: **Enter** para hablar y Enter para terminar, **escribe** una frase para enviarla como texto, **h** te sugiere 3 cosas que podrías decir (conversación y roleplay), **r** repite la última respuesta, **q** sale.
Cada sesión se guarda en `sessions/` como Markdown.

## Niveles
El nivel (por defecto **B2**) cambia cómo habla el tutor, cómo conversa, qué phrasal verbs usa y lo exigente que es. Se define en `src/english_teacher/levels.py` y se inserta en los prompts mediante marcadores `{{...}}`.

| | B1 | B2 | C1 |
|---|---|---|---|
| Inglés del tutor | Sencillo, sin idioms | Natural, con idioms y collocations | Nativo culto, con matices |
| Conversación | 1-2 frases, pregunta sencilla | Preguntas abiertas (opiniones, hipótesis); te pide desarrollar las respuestas cortas; sugiere versiones más ricas | Además te lleva la contraria y señala vocabulario repetido y registro |
| Phrasal verbs | Lista común (88) | Común + avanzada (165) | Avanzada (77) |
| Personajes del roleplay | Colaboran, hablan claro | Naturales, ponen objeciones razonables | Difíciles: no ceden fácilmente, usan slang |
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
| `tenses` | Tiempos verbales complejos (present perfect continuous, past perfect, future perfect, condicionales 2.º/3.º/mixtos, wish, modales en perfecto, estilo indirecto...). Alterna preguntas que obligan a usar el tiempo con frases en español para traducir, pensadas para los errores que vienen del español ("llevo tres años...", "ojalá hubiera..."). Dos intentos; si fallas, te dice la versión correcta. La primera vez propone un diagnóstico (una frase por estructura) y después prioriza las que más te cuestan (`progress/tenses.json`, estructuras y frases en `data/tenses.yaml`). |
| `paraphrase` | El tutor habla ~30 s sobre un tema (noticia, opinión, anécdota o explicación; tema fijo o variado de `data/paraphrase_topics.txt`) y tú lo cuentas con tus palabras. El texto no se muestra hasta después (**r** para volver a escucharlo). Evalúa qué ideas clave cubriste, si dijiste algo incorrecto y el **% de copia literal** (secuencias de 3 palabras idénticas al original, calculado por el programa); después muestra tus errores, una versión modelo y el texto original. El siguiente texto se genera mientras lees. |
| `writing` | **Solo texto**, sin Whisper ni Kokoro. Le das un texto tuyo (`-f archivo` o pegándolo y Ctrl+D) y lo revisa por párrafos en dos pasos: **1. gramática** (solo errores reales, con la regla explicada en español) y **2. naturalidad** (lo que un nativo no diría así, con el porqué; las mejoras opcionales van marcadas aparte). El paso 2 se prepara mientras lees el paso 1. El modelo solo lista cambios y el programa los aplica, así que el texto final contiene exactamente los cambios explicados; el paso 2 no puede deshacer correcciones del paso 1. Gramática con **Qwen3 14B** en local (`-m` para cambiarlo); naturalidad con **OpenAI** (ver abajo). Guarda un informe en `writings/`. |
| `roleplay` | El tutor presenta una escena (hotel sin reserva, entrevista de trabajo, vuelo cancelado...) y un personaje con su propia voz habla contigo sin salirse del papel. Tienes un objetivo que conseguir; el personaje mete complicaciones en los turnos 3 y 6. Las correcciones salen en pantalla sin interrumpir la escena y al final hay un repaso hablado con tus errores más importantes y expresiones útiles. Puedes elegir una de las escenas de `data/scenarios/` o pedir que invente una (con un tema opcional). |
| `phrasal-verbs` | El tutor explica un phrasal verb en inglés con un ejemplo y tú creas una frase. Tienes 2 intentos; si fallas, te da un ejemplo y pasa al siguiente. Prioriza los verbos que no has visto o que más te cuestan (progreso en `progress/phrasal_verbs.json`, lista en `data/phrasal_verbs.txt`). |

Para añadir una escena: copia cualquier archivo de `data/scenarios/` y cambia los campos (`title` en español para el menú; el resto en inglés; `voice` es una voz de Kokoro distinta de `af_heart`, que es la del narrador).

Para añadir una práctica nueva: crea una subclase de `Practice` en `src/english_teacher/practices.py`, su prompt en `prompts/` y regístrala en `PRACTICES`. Si la práctica tiene que evaluar algo (correcto / incorrecto), usa el modo evaluado como `PhrasalVerbs`: una llamada con salida JSON evalúa y otra genera lo que dice el tutor. Con modelos de ~12B es mucho más fiable que pedir las dos cosas en una sola respuesta.

## Modelo en la nube (solo `writing`, paso de naturalidad)
Todo es local salvo el paso 2 de `writing`, que por defecto usa `openai:gpt-5.4-mini`: los modelos locales de ~14B no daban buenos resultados ahí. El texto de ese paso se envía a OpenAI (con `store=False`, para que no lo guarden).

```sh
set -Ux OPENAI_API_KEY sk-...                          # fish; la clave nunca va en el repositorio
uv run english-teacher writing -f texto.txt
uv run english-teacher writing --natural-model openai:gpt-5.4   # otro modelo (se guarda como predeterminado)
uv run english-teacher writing --natural-model qwen3:14b        # todo local
```
Sin clave o sin conexión, el paso 2 avisa y sigue con el modelo local. Consulta precios y modelos disponibles en la documentación de OpenAI.

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
