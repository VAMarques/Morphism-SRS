# Deuda Técnica — Morphism SRS

Este documento consolida la deuda técnica, código spaghetti, código legacy, herramientas de migración y parches de compatibilidad identificados durante la auditoría y actualización de la documentación técnica (`specZ`).

---

## Índice de Deuda Técnica
1. [Herramientas de Migración y Compatibilidad con Prototipos Anteriores](#1-herramientas-de-migración-y-compatibilidad-con-prototipos-anteriores)
2. [Arquitectura y Estructura de Proyecto](#2-arquitectura-y-estructura-de-proyecto)
3. [Base de Datos y Persistencia](#3-base-de-datos-y-persistencia)
4. [Temas y Estilos](#4-temas-y-estilos)
5. [Motor de Renderizado y WebEngine](#5-motor-de-renderizado-y-webengine)
6. [Algoritmo de Planificación FSRS](#6-algoritmo-de-planificación-fsrs)
7. [Compilador DSL y Formato MDSL](#7-compilador-dsl-y-formato-mdsl)
8. [Vistas de Interfaz y Navegador Masivo](#8-vistas-de-interfaz-y-navegador-masivo)
9. [Sincronización Móvil y Android](#9-sincronización-móvil-y-android)

---

## 1. Herramientas de Migración y Compatibilidad con Prototipos Anteriores

- **Migrador autónomo `migrate_proto1.py`**:
  - Ubicación: [`tools/migrate_proto1.py`](tools/migrate_proto1.py) y pruebas en [`tests/test_migrate_proto1.py`](tests/test_migrate_proto1.py).
  - Descripción: Script externo que parsea estructuras obsoletas basadas en carpetas (`Courses/`, `scheduling/`, archivos JSON sueltos) para convertirlas a SQLite v2.
  - Estado: Mantener mientras existan usuarios con datos previos a migrar, pero desacoplado del runtime del aplicativo.

- **Limpieza preventiva de carpetas legacy en `AppPaths`**:
  - Ubicación: [`src/morphism_srs/config.py`](src/morphism_srs/config.py#L52-L60).
  - Descripción: `AppPaths.__init__` ejecuta un `shutil.rmtree` silencioso sobre `%APPDATA%\Morphism` si existe, para unificar en `%APPDATA%\MorphismSRS`.
  - Deuda: Requiere manejo de excepciones con logging estructurado y eventual eliminación una vez consolidado el directorio estándar.

---

## 2. Arquitectura y Estructura de Proyecto

- **Divergencia en el Sistema de Deshacer (Undo/Redo)**:
  - Ubicación: [`src/morphism_srs/controllers/commands.py`](src/morphism_srs/controllers/commands.py) frente a `QUndoStack` de Qt.
  - Descripción: La arquitectura proyectaba subclases formales de `QUndoCommand` integradas con `QUndoStack` y estados diferenciales `state_before_json`/`state_after_json` en base de datos. La implementación actual utiliza `CommandStack` en memoria con closures `Callable[[], None]` (`undo_fn`, `redo_fn`), lo cual es volátil y no persiste entre reinicios ni soporta un historial persistente unificado en ventana principal.
  - Deuda: Consolidar formalmente el stack de deshacer para que opere sobre eventos transaccionales uniformes o persista un log de auditoría completo.

- **Cobertura parcial del Bus de Eventos (`EventBus`)**:
  - Ubicación: [`src/morphism_srs/controllers/event_bus.py`](src/morphism_srs/controllers/event_bus.py).
  - Descripción: El `EventBus` actual implementa un conjunto acotado de 9 señales (`courses_updated`, `course_selected`, `notes_updated`, etc.). Varios diálogos y vistas aún reciben referencias directas a repositorios o controladores en lugar de desacoplarse enteramente por eventos.

---

## 3. Base de Datos y Persistencia

- **Migraciones inline ad-hoc en `DatabaseManager.initialize()`**:
  - Ubicación: [`src/morphism_srs/storage/database.py`](src/morphism_srs/storage/database.py#L49-L102).
  - Descripción: Al iniciar la conexión, el gestor comprueba si `notes.course_id` tiene restricción `NOT NULL` de versiones tempranas y, de ser así, ejecuta una reconstrucción de tabla al vuelo (`CREATE TABLE notes_nullable_cid ... DROP TABLE notes ... RENAME`). Igualmente puebla `course_notes` desde `notes` si está vacía.
  - Deuda: Migrar estos parches preventivos a un sistema formal de versionado con `PRAGMA user_version` y scripts de migración incrementales numerados.

- **Ausencia de tabla relacional `card_media`**:
  - Ubicación: [`src/morphism_srs/storage/schema_v2.sql`](src/morphism_srs/storage/schema_v2.sql) y [`src/morphism_srs/storage/media_vault.py`](src/morphism_srs/storage/media_vault.py).
  - Descripción: Los assets se registran en `media_assets` y se referencian mediante URIs `morphism://media/<sha256>.<ext>` en el HTML de las notas y tarjetas, pero no existe una tabla de unión `card_media(card_id, media_sha256)`.
  - Deuda: Para implementar un recolector de basura (GC) de imágenes huérfanas o verificar integridad de medios en paquetes `.mpkg`, es necesario realizar un parseo o escaneo de strings sobre los campos HTML en vez de una consulta SQL relacional directa.

- **Borrado en cascada de `review_logs`**:
  - Ubicación: [`src/morphism_srs/storage/schema_v2.sql`](src/morphism_srs/storage/schema_v2.sql#L166).
  - Descripción: En el esquema real, `review_logs.card_id` tiene `ON DELETE CASCADE`. Si una tarjeta se elimina físicamente de la base de datos (hard delete), sus registros históricos de repaso se eliminan automáticamente, afectando métricas agregadas del heatmap histórico si no se utiliza borrado lógico.
  - Deuda: Evaluar la transición a `card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL` junto con una columna inmutable `historical_card_id` para preservar el historial analítico independiente de la existencia de la tarjeta.

---

## 4. Temas y Estilos

- **Reglas QSS duplicadas en `app.qss.tmpl`**:
  - Ubicación: [`src/morphism_srs/resources/styles/app.qss.tmpl`](src/morphism_srs/resources/styles/app.qss.tmpl#L199-L209) y líneas 228-238.
  - Descripción: El bloque de selectores para `QLineEdit[variant='secondary'], QLineEdit[role='filter']` está duplicado exactamente dos veces consecutivas en la plantilla maestra de estilos.
  - Deuda: Eliminar el bloque repetido en la plantilla QSS.

- **Inyección dinámica de variables CSS en WebViews**:
  - Ubicación: [`src/morphism_srs/theming/theme_manager.py`](src/morphism_srs/theming/theme_manager.py#L68-L75).
  - Descripción: `compile_css_variables_js()` genera un fragmento de JavaScript con múltiples llamadas a `document.documentElement.style.setProperty`, el cual debe ser ejecutado en cada vista web individual en lugar de disponer de un endpoint centralizado reactivo en el esquema URL `morphism://`.
  - Deuda: Centralizar la suscripción de recarga de variables CSS en las vistas web mediante `theme_changed`.

---

## 5. Motor de Renderizado y WebEngine

- **Re-renderizado de Elementos Hermanos (`siblings`) en Notas Seriales/Cloze**:
  - Ubicación: [`src/morphism_srs/resources/web/js/review_renderer.js`](src/morphism_srs/resources/web/js/review_renderer.js#L73-L81) y [`src/morphism_srs/ui/views/review_view.py`](src/morphism_srs/ui/views/review_view.py#L274-L297).
  - Descripción: Al transicionar de una tarjeta $A_i$ a $A_{i+1}$ dentro de la misma nota serial o cloze, `renderCardState(payload)` re-construye el HTML de todos los hermanos condicionales (`sibBefore` / `sibAfter`) y ejecuta `typesetElements([root])` sobre todo `#review-root`. Aunque la revelación de la respuesta (`revealAnswer`) optimiza el proceso procesando únicamente `[backEl]`, el avance de tarjeta re-renderiza los pasos previos ya visualizados en lugar de promover el nodo SVG existente en el DOM o utilizar una caché de fragmentos renderizados.
  - Deuda: Implementar una estrategia de promoción DOM incremental o caché en memoria de bloques MathJax renderizados para demostraciones matemáticas extensas con decenas de pasos.

- **Cola de compilación `_typesetQueue` sin descarte de operaciones intermedias en Preview**:
  - Ubicación: [`src/morphism_srs/resources/web/js/preview_renderer.js`](src/morphism_srs/resources/web/js/preview_renderer.js#L4-L22).
  - Descripción: Cuando el usuario escribe con rapidez en el editor de notas, cada actualización de texto encola una promesa de compilación en `_typesetQueue`. Si bien esto previene solapamiento de ejecución en Chromium, las tareas encoladas intermedias se ejecutan secuencialmente antes de llegar a la versión más reciente del texto.
  - Deuda: Incorporar un token de cancelación o debounce en la cola de MathJax en vistas previas para descartar compilaciones intermedias superadas por nuevo input.

---

## 6. Algoritmo de Planificación FSRS

- **Colapso de Retención Conjunta ($P_{\text{joint}}$) en Notas con Tarjetas Nuevas**:
  - Ubicación: [`src/morphism_srs/domain/scheduler_engine.py`](src/morphism_srs/domain/scheduler_engine.py#L168-L181).
  - Descripción: En `compute_note_metrics`, si una tarjeta está en estado `NEW` o carece de `last_review_at`, su retención individual se asigna como `0.0`. Por ende, el producto de retenciones conjuntas $P_{\text{joint}} = \prod_i R_i(t)$ colapsa a `0.0` para toda la nota mientras exista al menos una tarjeta sin repasar, enmascarando la retención de las tarjetas ya graduadas.
  - Deuda: Evaluar la opción de calcular $P_{\text{joint}}$ exclusivamente sobre el subconjunto de tarjetas activas ya evaluadas, o proveer una métrica diferencial `p_joint_active` vs `p_joint_overall`.

- **Carga Síncrona de Aristas en Ordenamiento Topológico**:
  - Ubicación: [`src/morphism_srs/controllers/review_controller.py`](src/morphism_srs/controllers/review_controller.py#L201-L208).
  - Descripción: Al iniciar sesiones masivas o globales con orden topológico, `_order_candidates` consulta síncronamente `list_edges_by_course` por cada curso involucrado dentro del hilo principal de la interfaz de usuario.
  - Deuda: Delegar la consulta de grafos y el cómputo del algoritmo de Kahn a un `QThread` o `QRunnable` para colecciones con miles de aristas.

---

## 7. Compilador DSL y Formato MDSL

- **Rutas de Búsqueda Hardcodeadas para Archivos Multimedia en `DSLCompiler`**:
  - Ubicación: [`src/morphism_srs/services/dsl_compiler/compiler.py`](src/morphism_srs/services/dsl_compiler/compiler.py#L60-L65).
  - Descripción: El método auxiliar `_find_media_file` incluye como candidatos carpetas de desarrollo hardcodeadas (`root / "to_import" / "media"`, `root / "to_import"`).
  - Deuda: Desacoplar la resolución de archivos multimedia para que dependa exclusivamente de `source_dir` pasado explícitamente o del almacén de medios del usuario.

- **Compilación Síncrona de Scripts `.mdsl` Masivos**:
  - Ubicación: [`src/morphism_srs/services/dsl_compiler/compiler.py`](src/morphism_srs/services/dsl_compiler/compiler.py#L140-L150).
  - Descripción: `compile_and_commit` ejecuta el parseo, validación semántica, sanitización regex de imágenes/matemáticas y transacción SQLite en el hilo de la interfaz. Para archivos MDSL de miles de líneas con decenas de imágenes vectoriales, puede ocasionar congelamientos momentáneos de la UI.
  - Deuda: Ejecutar la compilación e importación por lotes en un worker en segundo plano con reporte progresivo vía señales.

---

## 8. Vistas de Interfaz y Navegador Masivo

- **Menciones Hardcodeadas de "Prototype 2" en Títulos de MainWindow**:
  - Ubicación: [`src/morphism_srs/ui/main_window.py`](src/morphism_srs/ui/main_window.py#L53) y línea 107.
  - Descripción: `MainWindow.__init__` asigna el título `"Morphism SRS Prototype 2 (v...)"` y un label lateral `"Prototype 2 • v..."`.
  - Deuda: Homogeneizar la denominación consolidada de la versión a "Morphism SRS".

- **Ausencia de Paginación en `QTableView` de BrowserView**:
  - Ubicación: [`src/morphism_srs/ui/views/browser_view.py`](src/morphism_srs/ui/views/browser_view.py#L43-L105).
  - Descripción: `BrowserTableModel` almacena en memoria la lista completa `self._rows` recuperada por `BrowserRepository`. Si bien `QTableView` virtualiza el dibujo de filas visibles en pantalla, colecciones con más de 50,000 tarjetas mantendrán toda la lista de DTOs en RAM tras cada búsqueda.
  - Deuda: Implementar `canFetchMore` y `fetchMore` en `QAbstractTableModel` para carga perezosa bajo demanda con `LIMIT`/`OFFSET` o cursor en SQLite.

---

## 9. Sincronización Móvil y Android

- **Rutas legacy no autenticadas en `EphemeralMobileServer` y mutación directa de `ReviewController`**:
  - Ubicación: [`src/morphism_srs/services/mobile_server.py`](src/morphism_srs/services/mobile_server.py#L175-L207) y [`#L283-L298`](src/morphism_srs/services/mobile_server.py#L283-L298).
  - Descripción: El endpoint `/api/checkin` procesa repasos forzando `review_controller._queue = [card]` y ejecutando `submit_rating()`. Si el usuario tiene una sesión de estudio activa en el escritorio, esto altera el puntero de índice y la cola en memoria del controlador de repaso. Además, la compatibilidad con rutas v2 y v1 en texto plano requiere banderas de compatibilidad (`allow_legacy`).
  - Deuda: Desacoplar las rutas legadas o eliminarlas definitivamente en favor del protocolo v3 transaccional (`push_delta`), que opera de manera atómica y pura sobre SQLite sin alterar la sesión de UI en memoria.

- **Aliasing de rutas internas v3 a v2**:
  - Ubicación: [`src/morphism_srs/services/mobile_server.py`](src/morphism_srs/services/mobile_server.py#L149-L150) y [`#L250`](src/morphism_srs/services/mobile_server.py#L250).
  - Descripción: En el servidor HTTP, las rutas entrantes `/api/v3/` se normalizan mediante `path.replace("/api/v3/", "/api/v2/", 1)`, lo que genera una superposición y posible confusión semántica entre el esquema de cifrado de red v3 y los controladores de ruta v2.
  - Deuda: Unificar el despachador de rutas para que despache explícitamente a manejadores con nombres propios de v3 (`handle_v3_pull_delta`, etc.).

- **Recálculo secuencial de horarios FSRS en `push_delta`**:
  - Ubicación: [`src/morphism_srs/services/delta_sync.py`](src/morphism_srs/services/delta_sync.py#L163-L186).
  - Descripción: Durante la ingesta de un lote de repasos móviles, cada tarjeta afectada requiere consultar la jerarquía de retención en base de datos, reconstruir los pesos FSRS efectivos y re-simular el historial completo en Python. En sincronizaciones con cientos de tarjetas afectadas, esto genera latencia acumulada dentro de la transacción de SQLite.
  - Deuda: Cachear los pesos resueltos por curso/carpeta e implementar recálculo en bloque o delegado a un worker asíncrono si el lote de tarjetas es masivo.

- **Caracteres corruptos (Encoding) en cadenas UI de `MobileQRDialog`**:
  - Ubicación: [`src/morphism_srs/ui/dialogs/mobile_qr_dialog.py`](src/morphism_srs/ui/dialogs/mobile_qr_dialog.py#L67), [`#L96`](src/morphism_srs/ui/dialogs/mobile_qr_dialog.py#L96) y [`#L107`](src/morphism_srs/ui/dialogs/mobile_qr_dialog.py#L107).
  - Descripción: Caracteres especiales como guiones largos o acentos aparecen como signos de interrogación (`?`) en las cadenas de texto visibles al usuario (`"📱 Morphism Mobile ? Sync v3"`, `"colecci?n"`, `"? AES-256-GCM ? sesi?n"`).
  - Deuda: Corregir los literales de cadena en el diálogo para utilizar caracteres UTF-8 correctos (o secuencias de escape unicode) sin modificar la funcionalidad.
