# Morphism SRS para Android

Compañero de estudio GPL-3.0-or-later para Android 8.0/API 26 o posterior.
Conserva la interfaz táctil anterior: grafo, repaso, cursos y estadísticas, con
los diez temas de escritorio. La base SQLite, los repasos FSRS 5, el historial
y el deshacer viven en Kotlin. No hay almacenamiento de cursos en localStorage,
autoría, importación ni exportación desde el móvil.

## Compilar

Desde la raíz del repositorio, con Python 3.11+ y las dependencias del proyecto:

```sh
python -m pip install -e .
python src/morphism-portable/build_portable.py
```

La primera compilación descarga JDK 17 de Adoptium, Kotlin CLI 2.0.21,
Android Build Tools 35 y plataforma API 34 desde sus distribuidores oficiales.
Windows y Linux x64 están soportados. Después se puede compilar sin conexión.
`JAVA_HOME` y `ANDROID_HOME` permiten reutilizar herramientas instaladas.
Los recursos SQL, CSS, MathJax, macros, temas e iconos se toman del escritorio
en cada compilación. `--prepare-only` copia esos recursos sin descargar herramientas.

El resultado es `morphism-srs.apk` en la raíz, alineado y firmado con v1/v2
(también v3 cuando lo permite apksigner). La clave de desarrollo persiste en
`.build_cache/portable/portable-debug.keystore`: consérvala para instalar futuras
actualizaciones. El builder no reutiliza un APK de otra aplicación.

## Sincronizar

1. Instala el APK y conecta ambos equipos a la misma red.
2. En el PC abre el diálogo **QR Móvil** y mantenlo abierto.
3. En Android pulsa **Sincronizar** y pega la URL completa que incluye el token.
4. Sincroniza antes de estudiar y nuevamente al terminar. El estudio funciona
   sin conexión entre sincronizaciones; los cambios estructurales se hacen en PC.

La primera sincronización replica todas las tablas y vincula el móvil al UUID
de esa base del PC. Las siguientes envían únicamente repasos pendientes y
deshacer; reciben cambios y borrados desde el cursor `sync_oplog`. Las imágenes
faltantes se descargan y verifican con SHA-256 antes de confirmar el cursor.
Un error de red permite repetir la operación sin duplicar repasos. Si ambos
dispositivos repasan una tarjeta, el PC recompone su horario reproduciendo todos
los registros por fecha y UUID con FSRS 5. Los horarios arbitrarios recibidos del
cliente no reemplazan el historial autoritativo.

El móvil rechaza otra identidad de PC para evitar mezclar dos bases. Para
vincularlo a una colección diferente, sincroniza los repasos pendientes con el
PC original y luego borra los datos de la aplicación en Ajustes de Android.

## Datos y compatibilidad

- SQLite nativo con WAL, claves foráneas y transacciones. El esquema relacional
  es `morphism_srs/storage/schema_v2.sql`. Android antiguo sin `STRICT` conserva
  las mismas columnas y restricciones sin esa palabra clave. Si SQLite no tiene
  FTS5 o JSON1, se omiten únicamente los índices FTS y los triggers de oplog
  que dependan de ellos; el móvil usa una bandeja SQL propia para los repasos.
- `portable_outbox` asigna secuencias locales independientes de los IDs del PC;
  `portable_undo` conserva las instantáneas y `portable_undone` los tombstones.
  Los registros locales usan IDs negativos hasta recibir el ID canónico del PC.
- Las actualizaciones SQL preservan hijos; no se usa `REPLACE` sobre cursos,
  notas ni tarjetas. Los cursores avanzan en la misma transacción que los datos.
- Las notas compartidas usan el propietario canónico para programar su único
  horario, con pesos heredados de carpetas/globales y retención propia si existe.
- El puente sólo expone operaciones de estudio. WebView sirve recursos locales
  `morphism://app` y `morphism://media` y bloquea navegación externa.
- La dependencia de escritorio se limita a `fsrs>=5.1.3,<6`: FSRS 6 cambia pesos
  y fórmulas y no cumple la paridad de este protocolo.

Referencias matemáticas: [FSRS-5](https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm#fsrs-5)
y [py-fsrs 5.1.3](https://github.com/open-spaced-repetition/py-fsrs/tree/v5.1.3).
No se ha incorporado código de Anki ni AnkiDroid.

## Verificación

```sh
python -m unittest discover -s tests -v
```

`test_delta_sync_and_portable.py` prueba triggers, bootstrap/deltas, cascadas,
autenticación HTTP, reintentos, borrado, deshacer y convergencia concurrente.
`test_portable_scheduler_parity.py` ejecuta el planificador Kotlin en JVM y
compara 1.024 estados con Python, incluidos repasos cortos y pesos personalizados.
Requiere haber descargado el toolchain con el builder.
`test_portable_web.py` comprueba la presentación y MathJax offline en Chromium
de Qt con un puente de prueba. Estas pruebas no sustituyen una prueba del APK
en un dispositivo Android real.
