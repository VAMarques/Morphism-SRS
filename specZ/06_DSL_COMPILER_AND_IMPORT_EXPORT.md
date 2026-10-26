# 06 — Compilador DSL de Notas/Cursos (`.mdsl`) y Sistema de Importación/Exportación (`.mpkg`)

> [!IMPORTANT]
> Este documento especifica la arquitectura completa del **Compilador Declarativo de Notas/Tarjetas/Cursos (`.mdsl`)** y el **Sistema de Importación/Exportación Empaquetada (`.mpkg`)**, cumpliendo los requerimientos #9–17 y #29 de [`specZ/old/Future_version.md`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/old/Future_version.md):
> ```text
> Card/Note/Course compiler using a format like
> NEW NOTE "name"
> CARD 1 "name1"
> FRONT
> xxx
> BACK
> aaa
>
> LINK "name" "othername"
> ```
> e integrando las decisiones del esquema v2: eliminación de `KIND` en favor de [`specZ/tags_default.csv`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/tags_default.csv), modos `standard | serial | cloze` ($P(A_i \mid \{A_j : j \ne i\})$), sanitización automática de `<` y `>` a `\lt` y `\gt`, soporte de diagramas vectoriales **SVG** y UUIDs universales.

---

## 1. Motivación: ¿Por qué un Compilador DSL Nativo (`.mdsl`)?

En el Prototipo 1 (documentado en `to_import/README.md`), la creación masiva de notas de matemáticas en JSON sufría un problema grave:
- En $\LaTeX$, expresiones como `\frac{1}{2}`, `\mathbb{R}`, `\beta`, `\tau`, `\nabla` comienzan con `\f`, `\b`, `\t`, `\n`, que el parser estándar de JSON interpreta como caracteres de control (*formfeed*, *backspace*, *tab*, *newline*), corrompiendo las fórmulas o lanzando `JSONDecodeError`.
- Para evitarlo, era necesario escribir scripts intermedios en Python (`scratch/build_...py`) usando raw strings `r"""..."""` solo para generar un archivo `.json` y luego importarlo manualmente desde la pestaña Courses.

Con el **Compilador Morphism DSL (`.mdsl`)**:
1. **Cero Escapes de Barra Invertida (`\`) ni Comillas (`"`)**: Todo el texto debajo de `FRONT` y `BACK` se lee literalmente como un bloque crudo (`RawContentBlock`) hasta la siguiente palabra clave estructural en inicio de línea. Puedes pegar $\LaTeX$ y HTML directamente desde un libro, un PDF o un LLM (Claude/GPT/Gemini) sin escapar absolutamente nada.
2. **Inmunidad Automática en Desigualdades (`<` y `>`)**: El compilador pasa cada bloque `FRONT` y `BACK` por `sanitize_math_html()` (definido en [`03_THEMING_QSS_AND_CSS_ARCHITECTURE.md`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/03_THEMING_QSS_AND_CSS_ARCHITECTURE.md#L334-L386)), convirtiendo `<` y `>` dentro de fórmulas a macros LaTeX nativas **`\lt`** y **`\gt`** y preservando etiquetas HTML válidas (`<b>`, `<br>`, `<ul>`, `<img>`).
3. **Prompts de IA 3 Veces Más Cortos e Infalibles**: Un LLM nunca falla al generar bloques `NEW NOTE` / `CARD` / `FRONT` / `BACK` / `LINK`, mientras que en JSON suele fallar al olvidar escapar una comilla o una barra invertida en una demostración de 15 pasos.
4. **Resolución Simbólica de Enlaces (`LINK "Nota A" "Nota B"`)**: No necesitas conocer IDs numéricos ni índices de arreglo (`"0" -> "1"`). El compilador enlaza notas por su título exacto (tanto entre notas nuevas del mismo script como hacia notas que ya existen en el curso dentro de SQLite).

---

## 2. Especificación Formal del Lenguaje Morphism DSL (`.mdsl`)

### 2.1 Ejemplo Completo de un Archivo / Script `.mdsl` (Los 3 Modos: `standard`, `serial`, `cloze`)

```text
# ============================================================================
# Morphism DSL (.mdsl) — Ejemplo: Análisis Real y Topología Métrica
# Los comentarios empiezan con '#' al inicio de una línea.
# Los tags siguen el formato snake_case de specZ/tags_default.csv.
# ============================================================================

COURSE "Análisis Real I"
FOLDER "Mathematics/Analysis"

# ----------------------------------------------------------------------------
# 1. Nota Estándar (Múltiples definiciones independientes: evalúa P(A_i))
# ----------------------------------------------------------------------------
NEW NOTE "Medida Exterior de Lebesgue"
MODE standard
TAGS definition, real_analysis, measure_theory, lebesgue_measure

CARD 1 "Definición de Medida Exterior m*(E)"
FRONT
Sea $E \subset \mathbb{R}^d$. ¿Cómo se define la <strong>medida exterior de Lebesgue</strong> $m_*(E)$ mediante recubrimientos por cubos cerrados?
BACK
Se define como el ínfimo de las sumas de volúmenes de recubrimientos numerables por cubos cerrados $Q_j$:
$$m_*(E) = \inf \left\{ \sum_{j=1}^{\infty} |Q_j| : E \subset \bigcup_{j=1}^{\infty} Q_j \right\}$$

CARD 2 "Subaditividad Numerable de m*"
FRONT
Enuncie la propiedad de <strong>subaditividad numerable</strong> de la medida exterior $m_*$.
BACK
Si $E = \bigcup_{j=1}^{\infty} E_j$ es una unión numerable de subconjuntos de $\mathbb{R}^d$, entonces:
$$m_*\left(\bigcup_{j=1}^{\infty} E_j\right) \le \sum_{j=1}^{\infty} m_*(E_j)$$

# ----------------------------------------------------------------------------
# 2. Nota Serial (Demostración encadenada paso a paso: evalúa P(A_i | A_1..A_{i-1}))
# ----------------------------------------------------------------------------
NEW NOTE "Demo: Subaditividad Numerable de la Medida Exterior"
MODE serial
TAGS theorem, proof, real_analysis, measure_theory, lebesgue_measure
RETENTION 0.88

CARD 1 "Paso 1: Reducción al caso de medida finita y elección del recubrimiento ε/2^j"
FRONT
Sea $E = \bigcup_{j=1}^\infty E_j$. ¿Por qué podemos asumir $m_*(E_j) < \infty$ para todo $j$, y cómo elegimos el recubrimiento $\{Q_{j,k}\}_{k=1}^\infty$ para cada $E_j$ dado $\varepsilon > 0$?
BACK
Si $m_*(E_j) = \infty$ para algún $j$, la desigualdad es trivial. Si $m_*(E_j) < \infty$ para todo $j$, por definición de ínfimo existe para cada $j$ una familia de cubos cerrados $\{Q_{j,k}\}_{k=1}^\infty$ tal que $E_j \subset \bigcup_{k=1}^\infty Q_{j,k}$ y:
$$\sum_{k=1}^{\infty} |Q_{j,k}| \le m_*(E_j) + \frac{\varepsilon}{2^j}$$

CARD 2 "Paso 2: Recubrimiento conjunto y serie geométrica"
FRONT
¿Cómo acotamos $m_*(E)$ usando la familia doble $\{Q_{j,k}\}_{j,k \ge 1}$ y cómo concluimos la demostración al hacer $\varepsilon \to 0^+$?
BACK
La familia numerable $\{Q_{j,k}\}_{j,k \ge 1}$ cubre a $E = \bigcup_{j=1}^\infty E_j$. Por tanto:
$$m_*(E) \le \sum_{j=1}^{\infty} \sum_{k=1}^{\infty} |Q_{j,k}| \le \sum_{j=1}^{\infty} \left(m_*(E_j) + \frac{\varepsilon}{2^j}\right) = \sum_{j=1}^{\infty} m_*(E_j) + \varepsilon$$
Como $\varepsilon > 0$ es arbitrario, se concluye que $m_*(E) \le \sum_{j=1}^\infty m_*(E_j)$. $\blacksquare$

# ----------------------------------------------------------------------------
# 3. Nota Cloze (Condicionamiento Holístico: evalúa P(A_i | {A_j : j != i}))
# ----------------------------------------------------------------------------
NEW NOTE "Caracterizaciones Equivalentes de Compacidad en Espacios Métricos"
MODE cloze
TAGS theorem, general_topology, metric_spaces, compactness

CARD 1 "1. Compacidad por Recubrimientos Abiertos (Borel-Lebesgue)"
FRONT
Dado el contexto de las demás caracterizaciones equivalentes de compacidad en un espacio métrico $(X, d)$, enuncie la condición de <strong>Borel-Lebesgue</strong> (por recubrimientos abiertos).
BACK
Todo recubrimiento abierto $\{U_\alpha\}_{\alpha \in I}$ de $X$ admite un subrecubrimiento finito $\{U_{\alpha_1}, \dots, U_{\alpha_m}\}$.

CARD 2 "2. Compacidad Secuencial (Bolzano-Weierstrass)"
FRONT
Dado el contexto de las demás caracterizaciones de compacidad en $(X, d)$, enuncie la condición de <strong>Compacidad Secuencial</strong>.
BACK
Toda sucesión $(x_n)_{n=1}^\infty$ en $X$ posee al menos una subsucesión $(x_{n_k})$ que converge a un punto $x \in X$.

CARD 3 "3. Completitud y Total Acotación"
FRONT
Dado el contexto de las demás caracterizaciones de compacidad en $(X, d)$, ¿qué dos propiedades métricas combinadas equivalen a que $(X, d)$ sea compacto?
BACK
$(X, d)$ es <strong>completo</strong> (toda sucesión de Cauchy converge en $X$) y <strong>totalmente acotado</strong> (para todo $\varepsilon > 0$ existe una $\varepsilon$-red finita).

# ----------------------------------------------------------------------------
# 4. Enlaces del Grafo (Prerrequisitos y Relaciones)
# ----------------------------------------------------------------------------
LINK "Medida Exterior de Lebesgue" -> "Demo: Subaditividad Numerable de la Medida Exterior"
# También se admite la sintaxis sin flecha especificada en Future_version.md:
LINK "Caracterizaciones Equivalentes de Compacidad en Espacios Métricos" "Medida Exterior de Lebesgue" TYPE related
```

---

### 2.2 Gramática Formal (EBNF)

```ebnf
Document        ::= ( BlankLine | Comment | Directive | NoteBlock | LinkStmt )* ;

Directive       ::= CourseStmt | FolderStmt | DefaultTagsStmt | DefaultModeStmt ;
CourseStmt      ::= "COURSE" QuotedString EOL ;
FolderStmt      ::= "FOLDER" QuotedString EOL ;
DefaultTagsStmt ::= "DEFAULT_TAGS" TagList EOL ;
DefaultModeStmt ::= "DEFAULT_MODE" ReviewMode EOL ;

NoteBlock       ::= ("NEW NOTE" | "NOTE") QuotedString EOL
                    NoteMetaStmt*
                    CardBlock+ ;

NoteMetaStmt    ::= ("MODE" ReviewMode EOL)
                  | ("TAGS" TagList EOL)
                  | ("RETENTION" FloatNumber EOL)
                  | ("POS" FloatNumber FloatNumber EOL) ;

ReviewMode      ::= "standard" | "serial" | "cloze"
                  | "serial_sequence_single" | "serial_sequence" ; (* Alias retrocompatibles -> 'serial' *)

CardBlock       ::= "CARD" [Integer] [QuotedString] EOL
                    "FRONT" EOL
                    RawContentBlock
                    "BACK" EOL
                    RawContentBlock ;

LinkStmt        ::= "LINK" QuotedString ["->"] QuotedString ["TYPE" RelationType] ["LABEL" QuotedString] EOL ;
RelationType    ::= "prerequisite" | "related" | "uses" | "generalizes" | "interferes" ;

TagList         ::= TagIdentifier ("," TagIdentifier)* ;
TagIdentifier   ::= (* snake_case identifier, e.g. theorem, real_analysis, measure_theory *) ;
RawContentBlock ::= (* Todas las líneas de texto literal hasta encontrar una línea cuyo
                       contenido recortado coincida con un Keyword de bloque:
                       ^(NEW NOTE|NOTE|CARD|FRONT|BACK|LINK|COURSE|FOLDER|END)\b *) ;
```

### 2.3 Reglas de Parsing Seguras para `RawContentBlock`
1. **Palabras clave reservadas sólo a nivel de línea completa**: Una palabra como `CARD` o `BACK` sólo se interpreta como delimitador si aparece al comienzo de la línea (ignorando espacios iniciales) y coincide con el patrón exacto del encabezado (`^BACK\s*$`, `^FRONT\s*$`, `^CARD(?:\s+\d+)?(?:\s+"[^"]*")?\s*$`, `^(?:NEW\s+)?NOTE\s+"[^"]+"\s*$`, `^LINK\s+"[^"]+"`).
2. **Escape explícito opcional (`\FRONT`, `\BACK`)**: Si en algún caso rarísimo una línea de un texto matemático necesitara contener únicamente la palabra `BACK` sola en una línea, escribir `\BACK` la escapa.
3. **Sanitización de `<` y `>` y Auto-conversión de Saltos de Línea**:
   - Todo bloque `FRONT` y `BACK` pasa por `sanitize_math_html()` (convirtiendo `<` y `>` matemáticos a `\lt` y `\gt`).
   - Si un bloque no contiene etiquetas HTML de estructura (`<p>`, `<div>`, `<ul>`, `<ol>`, `<table>`, `<br>`), el compilador convierte automáticamente los párrafos separados por línea en blanco (`\n\n`) en `<p>...</p>` y los saltos simples fuera de entornos `$$...$$` en `<br>`.

---

## 3. Arquitectura del Compilador en 2 Pasadas (`services/dsl_compiler/`)

```mermaid
flowchart LR
    Input["Script .mdsl\n(Archivo o Scratchbook)"]
    Lexer["1. DSLLexer\n(Tokens + Line/Col)"]
    Parser["2. DSLParser\n(Construye AST)"]
    Validator["3. SemanticValidator\n(Tags CSV, Links & Sanitizer)"]
    Importer["4. SQLiteBatchImporter\n(UnitOfWork + Auto-Layout)"]
    DB[("SQLite morphism.db")]

    Input --> Lexer --> Parser --> Validator --> Importer --> DB
```

### Pasada 1: Análisis Léxico, Sintáctico, Normalización de Tags y Construcción del AST
- Si hay un error de sintaxis (por ejemplo, un `CARD` al que le falta su sección `BACK`, o un `RETENTION 1.5` fuera de rango), el `DSLParser` devuelve un objeto `CompilationDiagnostic(line, column, severity, message)` que la UI subraya en rojo en el editor con el número de línea exacto.
- **Normalización de Tags**: Convierte cada tag a minúsculas con guiones bajos (`snake_case`). Si coincide con una de las 2,000 etiquetas de [`specZ/tags_default.csv`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/tags_default.csv), se enlaza al tag estándar (`is_standard = 1`); si es un tag nuevo del usuario, lo crea con `is_standard = 0` e informa en el resumen de compilación.

### Pasada 2: Resolución de Nombres (`LINK`) y Auto-Posicionamiento Topológico
Cuando `SQLiteBatchImporter` ejecuta un AST válido dentro de un curso destino:
1. Crea un registro en `import_batches` (con `uuid`, `source = 'dsl'` y `source_text = raw_mdsl_text`) para trazabilidad completa.
2. **Upsert o Creación de Notas**:
   - Crea las nuevas notas con su `uuid` v4 e inserta las tarjetas atómicas en orden (`position = 0, 1, 2...`).
   - Si el usuario activa la opción *"Update existing notes with matching title"*, actualiza las tarjetas de la nota existente (guardando una copia previa en `card_revisions`).
3. **Resolución de `LINK "Source Title" "Target Title"`**:
   - Busca `"Source Title"` y `"Target Title"` primero en el diccionario de notas recién creadas en este lote, y si no está ahí, lo busca entre las notas ya existentes en el curso dentro de SQLite (`COLLATE NOCASE`).
   - Si alguno de los dos títulos no existe en el lote ni en el curso, emite una advertencia clara antes de hacer commit: *"Line 74: LINK target 'Teorema de Fubini' not found in script or active course"*.
4. **Auto-Layout Topológico Inteligente**:
   - Para las notas nuevas que no especificaron coordenadas `POS x y`, calcula su profundidad en el subgrafo importado y las coloca en columnas limpias a la derecha (o debajo) del *bounding box* actual del grafo del curso, sin encimarlas sobre nodos existentes.

---

## 4. Nuevo Sistema de Importación y Exportación (`.mpkg`, `.mdsl`, `.json`)

Para cumplir con los puntos #27 y #29 de [`specZ/old/Future_version.md`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/old/Future_version.md), Morphism SRS Prototype 2 introduce un sistema unificado de paquetes:

### 4.1 Formato Nativo de Paquete de Curso: `.mpkg` (Morphism Package)
Un archivo `.mpkg` es un archivo comprimido **ZIP estándar** con la siguiente estructura interna:

```text
Analisis_Real_Stein.mpkg (ZIP Archive)
├── manifest.json            # Versión del esquema, UUID del curso, fecha, conteo de notas/medios
├── course.json              # Notas (con UUIDs), tarjetas atómicas, tags, coordenadas (x,y) y enlaces
├── course.mdsl              # Versión legible en DSL generada automáticamente (para inspección humana)
├── scheduling.json          # (Opcional) Horarios FSRS e historial review_logs si se exporta como Backup
└── media/                   # Todos los archivos SVG y PNG referenciados en card_media
    ├── a3f89c12...4b.png
    └── f102e48a...9c.svg    # Diagramas conmutativos vectoriales incluidos
```

### 4.2 Dos Modos de Exportación Claramente Diferenciados
Al exportar un curso (o una carpeta completa de cursos), un diálogo ofrece dos modos:
1. **📦 Shareable Course Deck (`.mpkg` — Sin Datos Personales de Repaso)**:
   - Incluye todas las notas (con sus `uuid` universales), tarjetas, etiquetas, posiciones `(x, y)` del grafo, enlaces de prerrequisitos y todos los diagramas `.svg` e imágenes `.png` en `media/`.
   - **Excluye** `card_schedules` y `review_logs`. Ideal para compartir mazos con otros estudiantes o publicarlos en GitHub: gracias a los `uuid`, si el autor publica una versión actualizada del mazo, los usuarios que lo re-importen recibirán las correcciones de contenido sin perder su propio progreso FSRS.
2. **💾 Full Personal Backup (`.mpkg` o `.db` — Con Progreso FSRS e Historial)**:
   - Incluye además el estado exacto de `card_schedules` y todos los `review_logs` para respaldar o transferir el progreso entre dispositivos.

### 4.3 Importación Polimórfica Unificada
El diálogo `📥 Import...` acepta múltiples formatos mediante detección automática:
- **`.mpkg`**: Extrae las imágenes y diagramas `.svg` de `media/` hacia `<USER_DATA_DIR>/media/` (verificando su hash `SHA-256`), registra en `media_assets` e importa o fusiona el curso por `uuid` en SQLite.
- **`.mdsl` / `.txt`**: Ejecuta el compilador `DSLCompilerService` e importa las notas y enlaces al curso seleccionado (o al curso declarado en la directiva `COURSE "..."`).
- **`.json`**: Soporta tanto el formato JSON v2 como el formato antiguo de lotes de IA del Prototipo 1 (`to_import/*.json`), garantizando **100% de retrocompatibilidad** con los más de 30 archivos JSON ya creados en `New SRS Project/to_import/`.
