# 06 — Compilador DSL de Notas/Cursos (`.mdsl`) y Sistema de Importación/Exportación (`.mpkg`)

> [!IMPORTANT]
> Este documento especifica la arquitectura del **Compilador Declarativo Morphism DSL (`.mdsl`)** y el **Servicio de Importación/Exportación de Paquetes (`.mpkg`)** en **Morphism SRS**, integrando soporte nativo para los tres modos de nota (`standard`, `serial`, `cloze`), sanitización automática de operadores matemáticos a `\lt` y `\gt`, detección y procesamiento de diagramas vectoriales **SVG** e imágenes locales, preservación de UUIDs universales y persistencia relacional en SQLite.

---

## 1. Fundamentos del Formato Declarativo Morphism DSL (`.mdsl`)

La creación masiva y transcripción de notas matemáticas complejas en formatos de intercambio como JSON presenta limitaciones estructurales severas:
- En $\LaTeX$, expresiones esenciales como `\frac{1}{2}`, `\mathbb{R}`, `\beta`, `\tau`, `\nabla` inician con `\f`, `\b`, `\t`, `\n`, secuencias que los parsers estándar de JSON interpretan como caracteres de escape de control (*formfeed*, *backspace*, *tab*, *newline*), forzando doble escape (`\\frac`) o corrompiendo fórmulas.
- La representación de aristas en grafos mediante índices posicionales volátiles resulta frágil frente a inserciones intermedias o reordenamientos.

El formato **Morphism DSL (`.mdsl`)** resuelve estos inconvenientes:
1. **Cero Escapes de Barra Invertida (`\`) ni Comillas (`"`)**: Todo el texto bajo las directivas `FRONT` y `BACK` se procesa como un bloque crudo literal (`RawContentBlock`). Es posible transcribir $\LaTeX$ y marcado HTML directamente sin requerir secuencias de escape.
2. **Inmunidad Automática frente al Parser Web**: Cada bloque se procesa mediante [`sanitize_math_html()`](../src/morphism_srs/services/safe_html.py#L21), transformando `<` y `>` a `\lt ` y `\gt ` dentro de fórmulas matemáticas mientras preserva intactas las etiquetas HTML (`<b>`, `<br>`, `<ul>`, `<img>`).
3. **Generación Óptima Asistida por IA**: La estructura de bloques `NEW NOTE` / `CARD` / `FRONT` / `BACK` / `LINK` ofrece una sintaxis intuitiva y sin ambigüedades para la generación mediante modelos de lenguaje (LLMs).
4. **Resolución Simbólica de Enlaces (`LINK "Nota A" -> "Nota B"`)**: Las dependencias epistémicas del grafo se declaran por títulos simbólicos o UUIDs, resueltos de forma unificada por [`DSLCompiler`](../src/morphism_srs/services/dsl_compiler/compiler.py#L36) tanto entre notas del mismo archivo como hacia notas preexistentes en la base de datos.

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

CARD 2 "Subaditividad Numerable de m*" UUID d4b89e1a-5f21-4a88-8cf9-7b102830f9a1
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
# También se admite la sintaxis sin flecha explícita:
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

## 3. Arquitectura del Compilador ([`services/dsl_compiler/`](../src/morphism_srs/services/dsl_compiler/))

```mermaid
flowchart LR
    Input["Script .mdsl\n(Archivo o Scratchbook)"]
    Lexer["1. DSLLexer\n(Tokens + Line/Col)"]
    Parser["2. DSLParser\n(Construye AST)"]
    Validator["3. DSLValidator\n(Verificación Semántica)"]
    Compiler["4. DSLCompiler\n(UnitOfWork + Media + Layout)"]
    DB[("SQLite morphism.db")]

    Input --> Lexer --> Parser --> Validator --> Compiler --> DB
```

### 3.1 Pasada 1: Análisis Léxico, Sintáctico y Validación Semántica
- **Tokenización y AST**: [`DSLLexer`](../src/morphism_srs/services/dsl_compiler/lexer.py) escanea el flujo de caracteres y [`DSLParser`](../src/morphism_srs/services/dsl_compiler/parser.py) construye el árbol sintáctico estructurado (`DSLCourseAST`, compuesto por `DSLNoteNode`, `DSLCardNode` y `DSLLinkNode`).
- **Diagnósticos de Compilación**: Si se detecta un error de sintaxis o rango (e.g. un `CARD` sin bloque `BACK`, o una directiva `RETENTION` inválida), [`DSLValidator`](../src/morphism_srs/services/dsl_compiler/validator.py) genera instancias de `DSLDiagnostic(line, column, severity, message)`, permitiendo al editor subrayar la línea exacta con el problema.
- **Normalización de Tags**: Los tags se convierten a minúsculas con guiones bajos (`snake_case`) y se cotejan con los tags existentes en la base de datos.

### 3.2 Pasada 2: Procesamiento Multimedia, Persistencia Relacional y Auto-Layout
Cuando [`DSLCompiler.compile_and_commit`](../src/morphism_srs/services/dsl_compiler/compiler.py#L139-L368) ejecuta la transacción sobre la base de datos:
1. **Transacción Segura**: Todo el proceso se ejecuta dentro de un [`UnitOfWork`](../src/morphism_srs/storage/unit_of_work.py#L12).
2. **Resolución de Curso y Carpetas**:
   - Identifica el curso por UUID o nombre, o lo crea dentro de la jerarquía de carpetas correspondiente vía [`FolderRepository.ensure_folder_path`](../src/morphism_srs/storage/repositories/folder_repo.py).
3. **Procesamiento de Medios y Diagramas Vectoriales SVG**:
   - `_process_media_text` detecta referencias multimedia (`<img src="...">`, `![alt](...)`, `[IMAGE ...]`).
   - Almacena los archivos en el [`MediaVault`](../src/morphism_srs/storage/media_vault.py), renombrándolos según su hash SHA-256.
   - Para archivos `.svg`, genera el contenedor con máscara CSS dinámico:
     `<div class="diagram-mask-container"><div class="commutative-diagram-mask" style="-webkit-mask-image: url('morphism://media/{stored_name}'); mask-image: url('morphism://media/{stored_name}');" role="img" aria-label="{label}"></div></div>`.
4. **Emparejamiento de Notas y Tarjetas**:
   - Resuelve notas existentes por `uuid` o `external_key`, actualizando su contenido o insertando nuevas tuplas relacionales preservando los historiales de estudio si los UUIDs coinciden.
5. **Resolución de Enlaces (`LINK`)**:
   - Conecta las notas origen y destino buscando en las notas procesadas del lote y en las notas preexistentes del curso, creando las filas en `note_edges`.
6. **Auto-Layout Topológico Inteligente**:
   - Si `auto_layout=True`, [`LayoutService.layout_course`](../src/morphism_srs/services/layout_service.py) calcula posiciones ordenadas en el plano del grafo para las notas sin coordenadas `POS x y` explícitas.

---

## 4. Sistema de Empaquetado e Intercambio (`.mpkg`, `.mdsl`)

Morphism SRS implementa un esquema unificado de empaquetado e intercambio basado en SQLite relacional puro y texto declarativo MDSL:

### 4.1 Paquetes de Curso `.mpkg` ([`MpkgService`](../src/morphism_srs/services/import_export/mpkg_service.py))
Un archivo `.mpkg` es un archivo comprimido **ZIP estándar** que contiene exclusivamente una base de datos SQLite pura y la carpeta de activos multimedia:

```text
Analisis_Real_Stein.mpkg (ZIP Archive)
├── morphism.db              # Base de datos SQLite pura con esquema relacional completo (schema_v2.sql)
└── media/                   # Archivos SVG y PNG direccionados por su hash SHA-256
    ├── a3f89c12...4b.png
    └── f102e48a...9c.svg    # Diagramas conmutativos vectoriales incluidos
```

- La base de datos `morphism.db` incluida dentro del paquete es una base SQLite relacional completa con triggers, constraints y tablas maestras (`courses`, `course_folders`, `notes`, `cards`, `note_edges`, `tags`).
- Puede incluir opcionalmente el historial de repetición espaciada (`card_schedules` y `review_logs`) al exportar con `include_scheduling=True`.

### 4.2 Preservación de Tarjetas por UUID en MDSL y `.mpkg`
- Cada tarjeta (`cards`) posee un identificador `uuid` universal único.
- El compilador MDSL reconoce las tarjetas por directivas explícitas `UUID <uuid>`.
- Al re-compilar o re-importar un paquete, las tarjetas se emparejan por su `uuid` único, permitiendo reordenar o renombrar títulos sin resetear el estado FSRS (`card_schedules`).

### 4.3 Importación Unificada
El diálogo de importación del aplicativo procesa:
- **`.mpkg`**: [`MpkgService.import_mpkg`](../src/morphism_srs/services/import_export/mpkg_service.py) abre el archivo ZIP, transfiere los activos multimedia hacia el [`MediaVault`](../src/morphism_srs/storage/media_vault.py) registrándolos en `media_assets`, y realiza la fusión SQL en la base de datos principal.
- **`.mdsl` / `.txt`**: Compila el archivo declarativo mediante [`DSLCompiler.compile_and_commit`](../src/morphism_srs/services/dsl_compiler/compiler.py#L139), importando las notas, tarjetas y aristas del grafo.

---

## 5. Próximos Pasos y Roadmap (Backlog Estratégico)

> [!NOTE]
> Para la especificación detallada de la arquitectura modular multi-archivo, el precompilador headless (`.mdsl` $\to$ `.mpkg` sin interfaz gráfica) y las herramientas CLI (`morphism-cli`), consultar el documento oficial de backlog:
> 👉 [`specZ/TODO/MODULAR_MDSL_CLI_PRECOMPILER_ROADMAP.md`](TODO/MODULAR_MDSL_CLI_PRECOMPILER_ROADMAP.md)

