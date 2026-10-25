# Plan de Re-Merge (Clean Room) y Resolución de `problemas.md` para Morphism SRS Prototype 2

> [!IMPORTANT]
> **Filosofía de este Plan (Clean Room Architecture):**
> `Morphism-SRS-plus` avanzó rapidísimo añadiendo una APK nativa de Android, temas extra, optimizaciones de renderizado y atajos UX, pero acumuló una fuerte deuda técnica:
> 1. **Doble motor incompatible**: Mantiene simultáneamente `src/morphism/` (Prototipo 1 basado en JSON) y una copia literal de `src/morphism_srs/` (Prototipo 2 basado en SQLite v2).
> 2. **Arquitectura incorrecta de Cloze (`{{c1::answer::hint}}`)**: En `Morphism-SRS-plus` (tanto en su motor desktop viejo como en la APK de Android), las Cloze se implementaron estilo Anki (`ClozeCard` con brackets `{{c1::...}}` que rompen el parser TeX y obligaron a meter parches regex para partir delimitadores `$ ... $`). **Eso NO se va a portar.** En Prototype 2, una nota `MODE cloze` es un conjunto de proposiciones/tarjetas atómicas $(A_1, \dots, A_k)$ donde al evaluar la tarjeta $i$ se condiciona holísticamente mostrando todas las demás tarjetas hermanas $\{A_j : j \ne i\}$ como contexto verificado ($P(A_i \mid \{A_j : j \ne i\})$).
> 3. **APK acoplada a JSON de Proto 1**: La APK actual de `Morphism-SRS-plus` usa el formato JSON antiguo (`ClozeCard`, `ProofSequenceCard`, `SEED_COURSES` hardcodeados en `app.js` de 4,800 líneas). En Prototype 2 construiremos una **APK Clean Room v2** nativa que hable **100% el modelo de dominio v2** (`standard`, `serial`, `cloze` por tarjetas hermanas, UUIDv4, soporte `.mpkg` / `.json` v2 / `.mdsl` y sincronización completa por QR).

---

## Parte 1: Auditoría de `Morphism-SRS-plus` — ¿Qué portamos (Clean Room) y qué descartamos?

### ✅ Lo que SÍ vale la pena rescatar (reimplementado limpiamente en Proto 2)
1. **Toolchain y Arquitectura de APK Android Autónomo (`android/` + `scripts/build_apk.*`)**:
   - El enfoque de envolver una SPA offline de alto rendimiento en un `WebView` nativo ligero (`MainActivity.java`, `< 1 MB`, compilado con `aapt2` + `javac` + `d8`/`r8` + `uber-apk-signer`) es excelente porque no requiere Android Studio pesado y compila en 2 segundos.
   - **Cambio Clean Room**: Reescribir `android/app/src/main/assets/{index.html, app.js, graph.js, fsrs.js}` desde cero sobre el **Esquema v2 de Prototype 2** (nodos con siluetas Rectángulo/Rombo/Elipse, condicionamiento `serial` $j < i$ y `cloze` $j \ne i$, sin `SEED_COURSES` de 4,000 líneas incrustados en el código fuente, con lector de QR / cliente de sincronización total contra la PC e importador/exportador `.mpkg` y `.mdsl`).
3. **Cola Secuencial de Promesas MathJax y CSS Anti-Clipping Horizontal**:
   - Encadenar `MathJax.typesetPromise` en una cola serializada (`_typesetQueue = _typesetQueue.then(...)`) en [`review_renderer.js`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/resources/web/js/review_renderer.js) y [`preview_renderer.js`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/resources/web/js/preview_renderer.js) previene condiciones de carrera al pasar tarjetas rápido.
   - Las reglas CSS para `mjx-container[jax="SVG"]` (`overflow-x: auto`, `max-width: 100%`, scrollbars delgados) evitan que matrices o derivaciones largas corten la tarjeta en pantallas pequeñas o móviles.
4. **Catálogo Expandido de Temas JSON y Activos de Icono (`icon.ico` / `icon.png`)**:
   - Portar los temas adicionales (`Bisexual Midnight`, `Catppuccin Mocha`, `Nord`, `Dracula`, `Tokyo Night`, `Solarized Dark`, `GitHub Light`) adaptados limpiamente a los **tokens de diseño v2** (`src/morphism_srs/resources/themes/*.json`).
   - Recuperar `icon.ico` e `icon.png` dentro de `src/morphism_srs/resources/icons/` y configurarlos tanto en el ejecutable/ventana de Windows y Linux como en los mipmaps de Android.
5. **Buscador Rápido en el Graph Explorer (`Ctrl+F`) y Pantalla de Resumen de Sesión**:
   - Barra de filtrado rápido en el `ExplorerView` que atenúa (`opacity: 0.22`) los nodos que no coinciden y centra el primer resultado.
   - Resumen estadístico limpio al terminar la cola de repaso (conteo de tarjetas, tiempo, desglose `Again/Hard/Good/Easy`).

### ❌ Lo que DESCARTAMOS rotundamente (Deuda Técnica / AI Slop)
- ❌ Todo el directorio legacy `src/morphism/` y los shims de compatibilidad con el Prototipo 1.
- ❌ `ClozeCard` basado en regex `{{c1::respuesta::pista}}` y la partición artificial de bloques `$$...$$`.
- ❌ `ProofSequenceCard` como clase separada de tarjeta (en Proto 2 todas las tarjetas son `CardModel` atómicas y el modo `serial` pertenece a la `NoteModel`).
- ❌ Los 4 cursos universitarios hardcodeados dentro de `android/app/src/main/assets/app.js` (`SEED_COURSES` de 4,000 líneas) y los scripts generadores específicos (`scripts/courses_builder/`).

---

## Parte 2: Plan Detallado para Resolver `specZ/problemas.md` en Prototype 2

A continuación se detalla la causa raíz exacta en el código actual de `Morphism SRS proto2` para cada uno de los **15 puntos** de [`specZ/problemas.md`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/problemas.md) y cómo se implementará su solución:

### 1. *"Bulk select is buggy, moves around too much"*
- **Causa raíz**: En [`GraphNodeItem.itemChange`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/explorer_view.py#L338-L348), cuando el snapping está activo o cuando se arrastran múltiples nodos seleccionados a la vez, cada nodo calcula su posición o actualización de aristas de forma independiente, y en `RubberBandDrag` de `QGraphicsView`, al hacer clic y arrastrar sobre un grupo o cerca de un nodo, Qt interpreta deltas acumulados bruscos o re-evalúa el `sceneRect` dinámicamente mientras se mueve el mouse. Además, `setTransformationAnchor(AnchorUnderMouse)` interactúa mal con el auto-scroll del `RubberBandDrag` en los bordes del viewport.
- **Solución**:
  1. Fijar un `sceneRect` amplio y estable en [`GraphCanvasView`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/explorer_view.py#L358-L388) (ej. `(-15000, -15000, 30000, 30000)` expandible con margen suave) para que la escena jamás salte ni re-encuadre sola mientras se dibuja el rectángulo de selección o se mueven nodos en bloque.
  2. Cuando hay múltiples nodos seleccionados (`len(scene.selectedItems()) > 1`) y `snapping_enabled` es `True`, aplicar el snap al **delta de movimiento del nodo líder** (manteniendo el offset relativo exacto de los demás nodos del bloque) en lugar de colapsar o hacer saltar cada nodo individualmente a la grilla `300x130`.
  3. Cambiar `ViewportUpdateMode` a `BoundingRectViewportUpdate` y desactivar el auto-scroll errático durante el trazado del marquee.

### 2. *"Linking nodes is buggy: Nodes do not link, and shortcut does not appear in tooltip"*
- **Causa raíz**:
  1. En [`GraphCanvasView.mousePressEvent`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/explorer_view.py#L425-L466), se usa `item = self.itemAt(event.position().toPoint())` y se verifica `isinstance(item, GraphNodeItem)`. Aunque `GraphNodeItem` no tiene hijos gráficos directos, cuando `DragMode` está en `ScrollHandDrag` (`✋ Pan Mode`), Qt intercepta o altera el foco/selección en `mousePressEvent`, o si el usuario hace clic derecho -> *"Add Prerequisite"*, el menú contextual convierte las coordenadas con `self.canvas.itemAt(pos)` pero `customContextMenuRequested` está conectado a `self.canvas` mientras el mapeo se hace con `self.canvas.viewport().mapToGlobal(pos)` (desfase de scrollbars).
  2. Peor aún: ni en el tooltip de los nodos, ni en el menú contextual (`🔗 Add Prerequisite`), ni en la barra de herramientas aparece indicado el atajo `Shift + Click`.
- **Solución**:
  1. Crear un método auxiliar seguro `_node_at_viewport_pos(pos: QPoint) -> GraphNodeItem | None` en `GraphCanvasView` que mapee `mapToScene(pos)` y busque en `scene().items(scene_pt)` el primer `GraphNodeItem` (ignorando `GraphEdgeItem` y `temp_prereq_line`, que con `zValue = 10.0` bajo el cursor hacía que `self.itemAt()` devolviera `temp_prereq_line` en vez del `GraphNodeItem` destino, **¡por eso nunca conectaba al hacer clic!**).
  2. Mostrar el atajo claramente en el menú contextual (`🔗 Add Prerequisite (or Shift+Click 2 nodes)`) y en el tooltip de los nodos / herramientas del canvas.
  3. Añadir feedback visual claro en el nodo origen cuando se inicia un enlace con `Shift+Click` (resaltado de borde + línea punteada siguiendo el cursor igual que desde el menú contextual).

### 3, 4, 5 y 6. *Arquitectura N:M Curso–Nota, Soft-Delete (Desvincular), Inyección de Notas Externas y Separación de `NoteBrowserView` vs `CardBrowserView`*
> - *"Lack of note browser"*
> - *"In general: Note and Card browser do not necessarily need to show Courses (ie, the card browser only needs the note and the card step, while the note browser would only need to show a note) (courses refer to notes instead), card browser is bugged, steps are not recognized as respective cards."*
> - *"Can't soft-delete notes from Course (ie, to unlink, but to keep them in the database and note browser)"*
> - *"Can't inject outside notes into Course (Would be via the note browser I mentioned)"*

- **Causa raíz arquitectónica**:
  1. Actualmente en [`schema_v2.sql`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/storage/schema_v2.sql#L57-L72), la tabla `notes` tiene `course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE`. Es decir, una nota no puede existir sin un curso, ni puede pertenecer a varios cursos o quedar "suelta" en el repositorio global cuando se quita de un curso.
  2.En el `BrowserView` actual, la consulta SQL y la tabla obligan a `JOIN courses co ON co.id = n.course_id` y muestran la columna `Course`. Además, cuando se importan o editan pasos de una nota, `step_order` o la sincronización en `BrowserRepository` falla al distinguir/reconocer pasos individuales cuando no tienen `card_schedules` inicializados o por cómo se agrupan.
- **Solución Clean Room en Base de Datos, Dominio y UI**:
  1. **Desacoplar Notas de Cursos en `schema_v2.sql`**:
     - Las notas (`notes`) pasan a ser entidades globales de primer nivel en la base de datos (`course_id` en `notes` pasa a ser nullable o se reemplaza por una tabla relacional **`course_notes (course_id, note_id, pos_x, pos_y, is_pinned, PRIMARY KEY (course_id, note_id))`** con migración automática transparente).
     - Así, **"los cursos se refieren a las notas"**: una nota existe por sí misma en la base de datos (con su `uuid`, `title`, `review_mode`, `tags` y sus `cards`), y un Curso simplemente referencia qué notas están en su grafo DAG y en qué coordenadas `(pos_x, pos_y)` se dibujan.
  2. **Soft-Delete (Unlink from Course) vs Hard-Delete (Delete from Database)**:
     - En el Graph Explorer (`DeleteNoteDialog` y menú contextual del nodo), ofrecer dos acciones claras:
       - **🔗 Unlink from Course (Soft-Delete)**: Quita la nota de este Curso (y sus aristas en este curso), pero **conserva la nota, sus tarjetas y su historial FSRS intactos en la base de datos** (accesibles desde el Note Browser).
       - **🗑️ Delete Permanently from Database (Hard-Delete)**: Borra la nota y sus tarjetas de toda la base de datos.
  3. **Crear `NoteBrowserView` y reparar `CardBrowserView` (o modo dual conmutador limpio `Notes | Cards`)**:
     - **Note Browser**: Muestra únicamente las Notas (`Note Title`, `Mode`, `Cards Count`, `R_min`, `Due/New`, `Tags`, `UUID`) **sin columna Course**. Permite:
       - Buscar por FTS5, etiquetas o modo.
       - Crear/Editar/Borrar notas globalmente.
       - **📥 Inject Selected Note(s) into Course...**: Botón directo y opción de clic derecho para inyectar cualquier nota existente de la base de datos dentro del Curso activo (o elegir a qué Curso inyectarla), colocándola en el DAG sin duplicar datos.
     - **Card Browser**: Muestra únicamente **`Note Title`, `Step / Card` (`#1: Card Title`), `Mode`, `State`, `R(t)`, `Stability`, `Due Date`, `Lapses`, `Tags`** (**sin columna Course**).
     - **Reparar el reconocimiento de Steps como Cards**: Asegurar en `NoteRepository` / `CardRepository` / `DSLCompiler` que cada paso (`CARD 1`, `CARD 2`, ..., o cada paso añadido en `NodeEditorDialog`) genere y sincronice su fila individual en `cards` y `card_schedules` con `step_order = 0, 1, 2...`, y que `BrowserRepository.search_cards` use `LEFT JOIN card_schedules` (creando horarios faltantes si hubiera alguno huérfano) para que **todos los steps de cada nota aparezcan siempre reconocidos como sus respectivas cartas**.

### 7, 8 y 9. *UUIDs de Notas en `.mdsl`, Exportación de Cursos visible y Regla de UUIDs solo en Notas*
> - *"(adding note uuid's into the .mdsl as to let replace notes and cards?) like NEW NOTE "Producto Interno" UUID (the uuid)"*
> - *"That is also very important for exporting Courses (Courses can't be exported yet, that would be very important, ie no button to export.)"*
> - *"Cards likely do not need uuid's as must be bound to a note"*

- **Causa raíz**:
  1. En [`DSLLexer`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/services/dsl_compiler/lexer.py#L38) y [`DSLParser`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/services/dsl_compiler/parser.py#L112-L120), `NEW NOTE "Título"` solo acepta el título y usa el título como `external_key`. Si cambias el título en el `.mdsl`, se crea una nota duplicada en vez de actualizar la nota existente.
  2. En [`CoursesView`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/courses_view.py#L152-L186), la barra superior tiene botón `📥 Import...`, pero **no tiene botón `📤 Export Course...`** (estaba escondido únicamente en el menú de clic derecho del árbol, por lo que parece que no existe).
- **Solución**:
  1. **Soporte de UUID en `.mdsl` (`NEW NOTE "Título" UUID <uuid>`)**:
     - Actualizar `DSLLexer` y `DSLParser` para aceptar opcionalmente `NEW NOTE "Producto Interno" UUID 550e8400-e29b-41d4-a716-446655440000` (o en línea separada `UUID <uuid>`).
     - Al compilar (`.mdsl` -> DB):
       - Si la directiva `NEW NOTE` trae `UUID`, buscar primero en `note_repo.get_by_uuid(uuid)`. Si existe, **actualizar esa misma nota** (título, modo, tags) y **reemplazar/sincronizar sus cartas por posición (`step_order`) preservando el historial FSRS** de los steps existentes (`0..k`). Si no trae `UUID`, buscar por título/external_key o generar un `UUIDv4` nuevo.
     - Al descompilar / exportar (DB -> `.mdsl` en `DSLCompiler.decompile_course`):
       - Emitir siempre `NEW NOTE "Título" UUID <note.uuid>`.
       - **Las cartas (`CARD 1 "Título"`) NO llevan UUID en `.mdsl`**, ya que están ligadas estrictamente a su nota padre por su índice `(note_id, step_order)`.
  2. **Botón Visible de Exportación en `CoursesView` (y en `ExplorerView`)**:
     - Añadir un botón explícito `📤 Export Course (.mdsl / .mpkg / .json)...` en la barra superior de [`CoursesView`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/courses_view.py) (que por defecto apunte a la carpeta `to_export/` en la raíz del proyecto para máxima comodidad).

### 10. *".mdsl needs image/SVG support (in to_import/media best idea)"*
- **Causa raíz**: Cuando un archivo `.mdsl` en `to_import/` incluye `<img src="media/diagrama.svg">` o `![diagrama](media/diagrama.png)`, `DSLCompiler.compile_and_commit` copia el string HTML literal sin importar el archivo desde `to_import/media/` hacia el `MediaVault` (`morphism://media/<sha256>.svg`), por lo que la imagen aparece rota.
- **Solución**:
  1. Crear la carpeta `to_import/media/` por defecto y documentarla en `to_import/README.md`.
  2. En `DSLCompiler.compile_and_commit(source, source_dir=...)` (pasando `media_vault`):
     - Detectar referencias a imágenes/SVGs en `FRONT` y `BACK`: tanto etiquetas HTML `<img src="media/foo.svg">` / `<img src="foo.png">` como sintaxis Markdown `![alt](media/foo.svg)` o directiva `[IMAGE "media/foo.svg"]`.
     - Resolver la ruta relativa respecto a `to_import/` y `to_import/media/`, almacenar automáticamente el archivo en `MediaVault` (`media_vault.store_file(...)`) y reescribir la etiqueta a `<img src="morphism://media/<sha256>.<ext>" class="commutative-diagram">`.
     - Al exportar a `.mpkg` o descompilar a `.mdsl` en `to_export/`, exportar también los archivos multimedia a `to_export/media/`.

### 11. *"\lt \gt were a bad idea, too buggy (the automatization, basically. Conversion to \lt, \gt should be ONLY inside math environments because else some non standard html becomes really buggy)"*
- **Causa raíz**: En [`safe_html.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/services/safe_html.py#L52-L78), `sanitize_math_html` intenta adivinar qué es un tag HTML con una lista blanca y convierte **todos los demás `<` y `>` de todo el texto** en `\lt ` y `\gt `. Si hay un tag HTML con atributos multilínea, comentarios, o texto fuera de LaTeX, lo corrompe metiendo `\lt ` y `\gt ` fuera de modo matemático.
- **Solución**:
  - Reescribir `sanitize_math_html(raw: str)` en [`safe_html.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/services/safe_html.py) para que **NO toque nada fuera de los delimitadores matemáticos**.
  - Únicamente dentro de bloques matemáticos explícitos (`$$...$$`, `\[...\]`, `$...$`, `\(...\)`), reemplazar `<` y `>` por `\lt ` y `\gt ` (evitando tocar tags HTML fuera de ellos). De esta forma, cualquier HTML fuera de `$ ... $` queda 100% intacto.
  - (Indicación extra: Esta conversión deberia ser al importar un .mdsl, pero la conversión no deberia pasar JIT, es decir, cuando importes un .mdsl, en la base de datos se convierte a \lt, pero si un usuario escribiera < o > esto no seria convertido automaticamente)

### 12. *"Remove phone sync, too buggy to be useful. But do not remove QR code, instead, just make sure an apk is ready, and make the QR code sync all data between pc and mobile"*
- **Causa raíz**: Actualmente [`mobile_server.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/services/mobile_server.py) sirve una mini-página web (`MOBILE_PWA_HTML`) para repasar en vivo en el navegador del teléfono o hacer check-out solo de la cola activa de repaso. Eso es frágil y limitado.
- **Solución (Full Bidirectional Database & Media Sync via QR + Standalone APK)**:
  1. **Eliminar la web-app de estudio por navegador (`MOBILE_PWA_HTML` / `/api/current` / `/api/rate`)**.
  2. **Convertir `MobileQRDialog` + `EphemeralMobileServer` en un "Full PC ↔ Mobile APK Data Sync" por QR**:
     - Al abrir `📱 Mobile QR Sync` en la PC, se levanta el servidor HTTP efímero en la LAN y se muestra el código QR (que codifica `{"url": "http://<lan_ip>:<port>", "token": "<secret>"}`) junto con la URL/código manual por si se usa sin cámara.
     - El servidor expone dos endpoints atómicos de sincronización completa:
       - `GET /api/v2/sync/pull?token=...`: Empaqueta y envía el estado completo de la base de datos SQLite v2 (carpetas, cursos, notas, tarjetas, horarios FSRS, logs de repaso, scratchbook y manifiesto de `media_assets` con descarga de SVGs/imágenes faltantes).
       - `POST /api/v2/sync/push?token=...`: Recibe desde la APK móvil el paquete de cambios/estado del teléfono (nuevos `review_logs`, actualizaciones de `card_schedules` comparadas por timestamp `last_review_at` / `updated_at`, cursos/notas creados o editados en el móvil) y hace un **merge transaccional idempotente por UUID** en la PC, devolviendo a su vez el estado consolidado al teléfono.
  3. **APK Móvil Nativa Funcional (`morphism-srs.apk`)**:
     - La APK móvil funciona 100% offline con toda tu colección sincronizada (Courses, Graph Explorer con formas v2, Review con modos `standard`/`serial`/`cloze` verdaderos, Note/Card Browser y Scratchbook).
     - En la APK habrá un botón **"🔄 Sync with PC (Scan QR / Connect)"**: escanea el QR de `MobileQRDialog` (usando `BarcodeDetector` / cámara del WebView o pegando el código/IP mostrado bajo el QR) y en 1 segundo sincroniza todos los cursos, notas, progreso FSRS e imágenes entre PC y móvil. También mantendrá importación/exportación directa de archivos `.mpkg` / `.mdsl` / `.json`.

### 13. *".ico is gone (ie, no app icon)"*
- **Causa raíz**: En `c:\repos\Morphism SRS proto2` no existe la carpeta `src/morphism_srs/resources/icons/` ni `icon.ico` / `icon.png`.
- **Solución**:
  - Copiar `icon.ico` e `icon.png` desde `Morphism-SRS-plus` (que provienen del proyecto original) hacia `src/morphism_srs/resources/icons/icon.ico` y `src/morphism_srs/resources/icons/icon.png` (y también en la raíz si se desea para empaquetado).
  - En [`app.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/app.py) y [`MainWindow`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/main_window.py#L54-L56), cargar `icon.ico` (preferido en Windows para la barra de tareas) con fallback a `icon.png`, y configurar el AppUserModelID en Windows (`ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("morphism.srs.proto2")`) para que Windows muestre el icono `.ico` en la barra de tareas y no el icono genérico de Python.
  (Indicación extra: es preferible copiarlo desde el repositorio original, carpeta New SRS Project)

### 15. *"Set default retrieval to 80%"*
- **Causa raíz**: Actualmente la retención deseada por defecto es `0.90` (90%) en [`config.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/config.py#L95), [`schema_v2.sql`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/storage/schema_v2.sql#L48), [`models.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/domain/models.py), [`scheduler_engine.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/domain/scheduler_engine.py#L64), [`courses_view.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/views/courses_view.py#L83), [`node_editor_dialog.py`](file:///c:/repos/Morphism%20SRS%20proto2/src/morphism_srs/ui/dialogs/node_editor_dialog.py#L183), etc.
- **Solución**:
  - Cambiar el valor por defecto de `desired_retention` / `default_desired_retention` a **`0.80` (80%)** en:
    - `config.py` (`DEFAULT_SETTINGS["default_desired_retention"] = 0.80`)
    - `schema_v2.sql` (`desired_retention REAL NOT NULL DEFAULT 0.80`)
    - `domain/models.py` (`CourseModel.desired_retention = 0.80`)
    - `domain/scheduler_engine.py` (`desired_retention: float = 0.80`)
    - `ui/views/courses_view.py`, `ui/views/explorer_view.py`, `ui/dialogs/node_editor_dialog.py`, `ui/dialogs/settings_dialog.py`, y `android/app/src/main/assets/fsrs.js`.

---

## Parte 3: Hoja de Ruta de Ejecución (Fases para Actualizar `proto2`)

Para implementar todo sin deuda técnica y con verificación continua (`pytest`), propongo ejecutar los cambios en **`c:\repos\Morphism SRS proto2`** en **5 fases limpias**:

1. **Fase 1 — Base de Datos v2.1, Modelo N:M Curso–Nota y Motor FSRS (Problemas #4, #5, #14, #15)**:
   - Migrar esquema para permitir notas desacopladas de cursos (`course_notes` / soft-delete de un curso sin borrar de la BD).
   - Eliminar `learning_steps` y `relearning_steps` en `SchedulerEngine`.
   - Configurar retención por defecto al **80% (`0.80`)** en toda la aplicación.
2. **Fase 2 — Sanitizador `\lt`/`\gt` Matemático, Compilador `.mdsl` (UUID + Imágenes/SVG) y Exportación (Problemas #7, #8, #9, #10, #11)**:
   - Restringir conversión de `<` y `>` a `\lt` y `\gt` exclusivamente dentro de delimitadores matemáticos (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`).
   - Soportar `NEW NOTE "Título" UUID <uuid>` en `.mdsl` (compilación con reemplazo in-place y descompilación con UUID de nota, sin UUID en cartas).
   - Soporte de imágenes/SVGs desde `to_import/media/` hacia `MediaVault`.
   - Añadir botón visible `📤 Export Course...` en `CoursesView` y `ExplorerView`.
3. **Fase 3 — `NoteBrowserView` + `CardBrowserView` y Mejoras de `ExplorerView` (Problemas #1, #2, #3, #4, #5, #6, #13)**:
   - Separar/estructurar **Note Browser** (sin columna Course, con botón *Inject into Course*) y **Card Browser** (solo Note + Card Step + métricas FSRS, reconociendo todos los steps correctamente).
   - Añadir opción **Soft-Delete (Unlink from Course)** vs **Hard-Delete** en el Graph Explorer.
   - Corregir el bug de `Bulk Select` (estabilidad de `sceneRect` y delta-snapping grupal) y el bug de `Linking Nodes` (ignorar `temp_prereq_line` en `itemAt` + mostrar atajo `Shift+Click` en tooltips y menú).
   - Restaurar `icon.ico` / `icon.png`, portar los temas JSON limpios y añadir el `eventFilter` en `ReviewView` + cola de promesas MathJax.
4. **Fase 4 — Sincronización Completa PC ↔ Móvil por QR y APK Android Clean Room (Problema #12)**:
   - Reemplazar el servidor móvil de repaso web en `mobile_server.py` por el endpoint de **Full Sync Bidireccional (`/api/v2/sync/pull` y `/api/v2/sync/push`)** activado por `MobileQRDialog`.
   - Construir la aplicación Android en `android/` siguiendo el modelo exacto de Prototype 2 (tarjetas atómicas, modos `standard`/`serial`/`cloze` condicionales, grafo con formas geométricas v2, FSRS al 80% sin learning steps, escáner/cliente QR Sync e importador `.mpkg`/`.mdsl`).
   - Compilar y firmar `morphism-srs.apk` listo para instalar en el teléfono.
5. **Fase 5 — Suite de Tests Automatizados**:
   - Actualizar y ampliar `tests/` para cubrir el reemplazo por UUID en `.mdsl`, la importación de media desde `to_import/media/`, el soft-delete e inyección de notas entre cursos, el sanitizador matemático y el endpoint de full sync móvil.
