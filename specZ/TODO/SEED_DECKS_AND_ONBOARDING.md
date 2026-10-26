# TODO — Especificación de Mazos Semilla Introductorios y Onboarding de Testers

> [!NOTE]
> Este documento contiene el diseño conceptual y la planificación de los **Mazos Semilla Preinstalados (Starter Decks)** y la estrategia para conseguir usuarios testers (requerimiento #25 de [`specZ/old/Future_version.md`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/old/Future_version.md)).
> **Estado**: Ubicado en el backlog (`specZ/TODO/`) para ser implementado únicamente cuando el motor principal de **Morphism SRS Prototype 2** esté finalizado y los mazos hayan sido redactados y curados por el autor.

---

## 1. Visión y Objetivos

El propósito de los mazos semilla es evitar que un usuario nuevo o un tester abra la aplicación y se encuentre con un lienzo en blanco intimidante. Debe permitir que cualquier estudiante de matemáticas, física o ciencias de la computación pueda experimentar los 3 modos de estudio (`standard`, `serial`, `cloze`), el grafo DAG y los diagramas conmutativos SVG en menos de 2 minutos tras abrir el programa por primera vez.

---

## 2. Catálogo de Mazos Semilla Planificados (`resources/defaults/seed_courses/`)

Cuando se decida activar esta característica, se empaquetarán como archivos `.mpkg` o scripts `.mdsl` los siguientes 3 cursos iniciales:

### 2.1 Mazo 1: `🌟 Morphism SRS — Interactive Tutorial`
Un curso guiado de 5 notas que enseña cómo funciona la aplicación mientras lo estudias:
- **Nota 1 (`standard` — Rectángulo) — Fundamentos del Grafo y Atajos**:
  - Explica la navegación del lienzo infinito, selección múltiple Marquee y atajos principales (`Space` para revelar/aprobar, `1–4` para calificar, `Ctrl+Z` para deshacer cualquier calificación o acción).
- **Nota 2 (`serial` — Rombo) — Demostraciones Encadenadas Paso a Paso ($P(A_i \mid A_1, \dots, A_{i-1})$)**:
  - Una demostración clásica en 3 pasos (ej. *Irracionalidad de $\sqrt{2}$* o *Infinitud de los números primos*) que muestra cómo los pasos previos dominados ($A_1, A_2$) permanecen visibles en `#past-steps-list` mientras se evalúa el paso activo $A_3$.
- **Nota 3 (`cloze` — Elipse) — Sistemas de Equivalencia Condicionada ($P(A_i \mid \{A_j : j \ne i\})$)**:
  - Un teorema de caracterizaciones equivalentes ($A_1 \iff A_2 \iff A_3$) donde al evaluar una condición $A_i$, el estudiante visualiza como contexto explícito todas las demás condiciones $\{A_j : j \ne i\}$.
- **Nota 4 (`standard` — Rectángulo) — Creación Rápida de Notas con el Compilador DSL (`.mdsl`)**:
  - Muestra la sintaxis declarativa `NEW NOTE`, `MODE`, `TAGS`, `CARD`, `FRONT`, `BACK`, `LINK` y cómo pegar fórmulas $\LaTeX$ directamente sin escapar barras invertidas ni preocuparse por `<` o `>` (convertidos automáticamente a `\lt` y `\gt`).
- **Nota 5 (`standard` — Rectángulo) — Bóveda de Medios y Diagramas Conmutativos SVG**:
  - Muestra un diagrama conmutativo vectorial `.svg` (propiedad universal del producto tensorial o funtor adjunto) con adaptación automática al tema oscuro.

### 2.2 Mazo 2: `📐 Fundamentos de Análisis Real (Rudin / Stein)`
Una selección curada y pedagógicamente estructurada de notas de Análisis Matemático:
- Espacios Métricos y Topología en $\mathbb{R}^n$ (`standard`).
- Caracterizaciones Equivalentes de Compacidad en Espacios Métricos (`cloze`: Borel-Lebesgue, Bolzano-Weierstrass, Completitud + Total Acotación, Propiedad de Intersección Finita).
- Teorema de Heine-Borel y Teorema de Heine-Cantor (`serial`).
- Medida Exterior de Lebesgue $m_*(E)$ y Demostración de Subaditividad Numerable (`serial`).
- Teorema de Convergencia Monótona de Lebesgue y Lema de Fatou (`serial`).

### 2.3 Mazo 3: `⚡ Álgebra Lineal y Teoría de Operadores`
Demostraciones y equivalencias fundamentales de longitud media (2 a 4 tarjetas por nota):
- Condiciones Equivalentes de Invertibilidad de un Operador Lineal en Dimensión Finita (`cloze`).
- Teorema de la Dimensión / Rango-Nulidad (`serial`).
- Descomposición en Valores Singulares (SVD) y Teorema Espectral para Operadores Autoadjuntos (`serial`).

---

## 3. Protocolo de Distribución "Zero-Setup" para Testers

1. **Ejecutable Autocontenido (`PyInstaller`)**:
   - Script `scripts/build_release.py` que genera un paquete portable (`MorphismSRS-Windows-x64.zip` y `AppImage` en Linux) con Python, PySide6, SQLite, `tex-svg-full.js`, `chart.umd.min.js`, temas JSON y [`specZ/tags_default.csv`](file:///c:/repos/Morphism%20SRS%20proto2/specZ/tags_default.csv) pre-incluidos.
2. **Asistente de Primer Arranque (First-Run Opt-In)**:
   - Al detectar una base de datos `morphism.db` recién creada, ofrece un diálogo opcional:
     - `[✓] Import Interactive Tutorial & Sample Mathematics Decks`
     - `[ ] Start with an Empty Workspace`
