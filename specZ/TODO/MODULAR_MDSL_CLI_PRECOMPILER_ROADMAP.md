# TODO — Ecosistema Modular .mdsl, Precompilador Headless (.mdsl -> .mpkg) y Morphism CLI

> [!IMPORTANT]
> **ESTADO DEL DOCUMENTO: BACKLOG ESTRATÉGICO / NO IMPLEMENTAR TODAVÍA**
> Este documento define el diseño arquitectónico y los requerimientos futuros para la modularización de cursos en `.mdsl`, la creación de una herramienta de línea de comandos (`morphism-cli`) y un precompilador autónomo capaz de empaquetar repositorios completos en paquetes `.mpkg` sin necesidad de inicializar la interfaz gráfica de Morphism SRS.
> **No debe implementarse de forma inmediata en las versiones actuales del prototipo**, pero constituye un componente crítico para la escalabilidad, la creación masiva asistida por IA y la distribución de cursos.

---

## 1. Motivación y Problemática Detectada

### 1.1 Inviabilidad del Enfoque "Mega-Archivo" Monolítico
Actualmente, los decks de Morphism se conciben como un único archivo plano `.mdsl` que agrupa el curso entero (definiciones, lemas, teoremas, ejercicios y aristas DAG). En asignaturas de pregrado o posgrado (e.g. *Teoría de la Medida*, *Álgebra Abstracta*, *Química para Ingenieros*), esto genera archivos de **miles de líneas y cientos de kilobytes**.
- **Fracaso de Agentes IA**: Los modelos de lenguaje sufren truncamiento de tokens de salida, fatiga de contexto y rotura recurrente al realizar ediciones selectivas (`edit_file` / diffs) sobre archivos tan grandes. Asimismo, es imposible poner a varios subagentes a redactar diferentes capítulos en paralelo sobre un mismo archivo sin generar colisiones destructivas.
- **Mantenibilidad humana y Git**: Un solo archivo monolítico vuelve impracticables los Pull Requests granulares, la revisión por pares y el control de versiones ramificado.
- **Desajuste Pedagógico en SKILL y README**: La especificación inicial del formato (`SKILL.md` y `README.md`) se diseñó para snippets aislados y notas de prueba, no para la arquitectura real de un curso académico completo con jerarquía profunda, lemas auxiliares, apéndices y diagramas cruzados.

### 1.2 La Necesidad de un Precompilador Headless (`.mdsl` $\to$ `.mpkg`)
Actualmente, la compilación de un archivo `.mdsl` a la base de datos de Morphism depende de las capas internas de la aplicación de escritorio (`DSLCompiler`, `UnitOfWork`, conexiones directas a SQLite vía la UI de PySide6).
- **Problema**: Para crear un paquete instalable `.mpkg` (que es un ZIP con `morphism.db` SQLite y la carpeta `media/`), el usuario debe abrir manualmente la GUI de Morphism, importar el `.mdsl`, esperar la inserción en base de datos y luego exportar el curso a `.mpkg`.
- **Visión Futura**: Se requiere un **precompilador independiente (stand-alone)** que pueda ejecutarse en CI/CD, scripts locales o directamente por agentes IA en la terminal, transformando un árbol de archivos `.mdsl` directamente en un `.mpkg` listo para consumo, sin arrancar Qt ni la interfaz gráfica.

---

## 2. Arquitectura de Repositorio de Cursos (Morphism Project Source Tree)

Un curso extenso se organizará como un repositorio estructurado de código fuente:

```text
curso_teoria_de_la_medida/
├── morphism.toml                  # Manifiesto del curso y metadatos globales
├── media/                         # Diagramas SVG y assets locales referenciables
│   ├── caratheodory_mask.svg
│   └── dynkin_system.svg
├── 01_espacios_medibles/
│   ├── 01_definiciones.mdsl       # Notas atómicas standard/cloze (~100-200 líneas)
│   ├── 02_propiedades.mdsl
│   └── 03_pi_lambda_theorem.mdsl
├── 02_medidas_exteriores/
│   ├── 01_construccion.mdsl
│   └── 02_caratheodory_proof.mdsl # Nota serial con la demostración encadenada
├── 03_integracion_lebesgue/
│   ├── 01_funciones_simples.mdsl
│   └── 02_convergencia_monotona.mdsl
└── topology/
    └── course_dag.mdsl            # Aristas y enlaces inter-capítulo del grafo
```

### 2.1 Manifiesto Declarativo `morphism.toml`
Desacopla la configuración del curso del contenido de las notas:
```toml
[course]
name = "Teoría de la Medida y Probabilidades (MAT253I)"
uuid = "e3b0c442-98fc-1c14-9afb-4c8996fb9242"
folder = "Matemáticas/Análisis Real"
color_hex = "#89b4fa"
desired_retention = 0.85
description = "Curso riguroso basado en Folland y Royden, con cobertura completa de Carathéodory, Radon-Nikodym y Fubini."

[build]
# Archivo de salida compilado
output = "dist/teoria_de_la_medida.mpkg"

# Inclusión por patrones glob
include = [
    "01_*/*.mdsl",
    "02_*/*.mdsl",
    "03_*/*.mdsl",
    "topology/*.mdsl"
]

# Validación estricta en compilación
strict_links = true           # Falla si hay enlaces a notas que no existen
auto_layout_engine = "dagre"   # Layout determinista de nodos sin POS explícito
```

---

## 3. Extensión de la Sintaxis `.mdsl`

Para soportar proyectos de gran escala sin ambigüedades:

1. **Directivas `INCLUDE` / `IMPORT` (Opcional si no se usa `morphism.toml`)**:
   ```text
   INCLUDE "01_espacios_medibles/01_definiciones.mdsl"
   INCLUDE "01_espacios_medibles/02_propiedades.mdsl"
   ```
2. **Identificadores Simbólicos Globales (`ID` / Namespaces)**:
   Evita colisiones de títulos idénticos entre diferentes asignaturas o capítulos:
   ```text
   NEW NOTE "Definición de Espacio Medible" ID "medida.sigma_algebra.espacio_medible"
   MODE standard
   TAGS teoria_de_la_medida, definicion
   ...
   ```
   Permitiendo enlazar inequívocamente:
   ```text
   LINK "medida.sigma_algebra.espacio_medible" -> "medida.caratheodory.teorema"
   ```
3. **Archivos de Topología Desacoplada (`course_dag.mdsl`)**:
   Permite que los redactores (humanos o agentes) se concentren en redactar contenido matemático puro en sus propios archivos, mientras un archivo central o submódulos declaran las dependencias epistémicas del DAG:
   ```text
   LINK "Definición de Medida Exterior" -> "Demostración: Teorema de Carathéodory"
   LINK "Lema de Fatou" -> "Teorema de Convergencia Dominada"
   ```

---

## 4. Diseño de la Herramienta CLI (`morphism-cli`)

Se planifica la creación de un paquete ejecutable ligero o módulo CLI: `morphism_srs.cli` (invocable como `python -m morphism_srs.cli` o binario `morphism`).

### Comandos Clave Planificados:
- `morphism check [path]`: Valida sintaxis, verifica que no haya enlaces rotos en el DAG (`dangling links`), valida fórmulas LaTeX básicas y reporta advertencias con línea y columna exacta.
- `morphism pack [project_dir] -o [output.mpkg]`:
  - Lee el árbol de fuentes y `morphism.toml`.
  - Construye una base de datos SQLite temporal en memoria con el esquema canónico `schema_v2.sql`.
  - Procesa e indexa todos los archivos `.mdsl`.
  - Empareja y copia los recursos de `media/` calculando hashes SHA-256.
  - Genera el archivo ZIP `.mpkg` con `morphism.db` y `/media` en su interior, 100% listo para importarse o distribuirse.
- `morphism bundle [project_dir] -o [monolith.mdsl]`:
  - Concatena y normaliza el repositorio entero en un único mega-archivo `.mdsl` autocontenido (útil para auditoría, debugging o importación de emergencia).
- `morphism unpack [input.mpkg] -d [target_dir]`:
  - Descompone un paquete `.mpkg` existente en un proyecto editable con carpetas y fuentes `.mdsl` decompilados.

---

## 5. Hoja de Ruta para su Futura Implementación (Roadmap)

Cuando se decida acometer este trabajo en fases posteriores, el plan de ejecución será:

1. **Fase A — Desacoplar el Compilador de la GUI**:
   - Refactorizar [`DSLCompiler`](../../src/morphism_srs/services/dsl_compiler/compiler.py) para que admita trabajar contra una base de datos SQLite efímera sin depender de servicios de la interfaz ni de singletons de Qt.
2. **Fase B — Implementar el Módulo `DSLLinker`**:
   - Crear un resolver de símbolos que reciba múltiples fragmentos de AST (`DSLCourseAST`) procedentes de varios archivos y los unifique en una sola tabla de símbolos antes de la inserción SQL.
3. **Fase C — Script de Empaquetado `MpkgPacker` Headless**:
   - Adaptar [`MpkgService`](../../src/morphism_srs/services/import_export/mpkg_service.py) para que construya el ZIP con `morphism.db` a partir de un directorio fuente sin pasar por la aplicación.
4. **Fase D — Actualización del SKILL y Guía de Generación de Mazos**:
   - Reescribir `.agents/skills/mdsl-format/SKILL.md` y `README.md` para instruir a los agentes a crear carpetas modulares por temas con notas atómicas en lugar de un único archivo gigante.
