# Morphism SRS ⚡

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![Platform: Desktop & Android](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS%20%7C%20Android-purple.svg)]()

**Morphism SRS** es un sistema de repetición espaciada (SRS) de código abierto diseñado desde cero para aprender y retener **Matemáticas avanzadas, Física teórica, Lógica formal y Demostraciones secuenciales**.

A diferencia de los sistemas tradicionales de flashcards, Morphism modela el conocimiento como un **grafo dirigido de conceptos y prerrequisitos**, adaptándose a cómo se razona, deduce y construye la matemática moderna.

---

## 🎯 ¿Por qué Morphism SRS?

Las herramientas clásicas de flashcards (como Anki) son excelentes para memorizar vocabulario o datos atómicos independientes. Sin embargo, **las matemáticas no son hechos aislados**: son una red interconectada de definiciones, lemas, teoremas y deducciones paso a paso, donde un razonamiento solo tiene sentido si comprendes los fundamentos previos.

Morphism SRS fue creado para resolver esto con dos pilares:
1. **Estructura matemática natural**: Grafos de dependencias (DAG), pasos de demostración encadenados y tarjetas con contexto mutuo.
2. **Flujo de creación asistido por IA ("AI Slop" amigable y masivo)**: Importa cursos enteros o libros de texto generados con LLMs en cuestión de segundos gracias a su lenguaje declarativo `.mdsl`.

---

## 💡 La Idea Principal: Matemáticas + Generación Masiva con IA

Crear tarjetas a mano, una por una, haciendo clic en formularios interminables es lento y agotador. Morphism SRS está pensado para aprovechar la era de los Modelos de Lenguaje (LLMs) de manera práctica:

1. **Generación con cualquier IA**: Puedes pasarle a Claude, ChatGPT, Gemini o a tu modelo local un temario, un libro de texto en PDF o tus apuntes de clase, y pedirle que genere decenas o cientos de tarjetas en el formato **Morphism DSL (`.mdsl`)**.
2. **LaTeX limpio sin caracteres de escape**: A diferencia de formatos rígidos como JSON (donde cada barra invertida de LaTeX debe escaparse como `\\frac` o `\\sum`), en `.mdsl` escribes fórmulas matemáticas estándar (`$...$` o `$$...$$`) de forma directa y legible.
3. **Importación inmediata**: Coloca tus archivos `.mdsl` en la carpeta `to_import/` (o pégalos directamente en el *Scratchbook* de la app) y Morphism compila al instante el grafo del curso, sus nodos, tarjetas y dependencias con programación FSRS lista para estudiar.

---

## 🌟 Características Principales

- 🗺️ **Explorador Visual de Grafos (DAG)**: Observa tus asignaturas como un mapa conceptual interactivo de prerrequisitos. Descubre qué conceptos desbloquean qué teoremas y repasa en orden lógico.
- 📐 **3 Modos de Repaso Epistemológicos**:
  - **Standard (Rectángulos)**: Tarjetas independientes para definiciones, enunciados y contraejemplos.
  - **Serial (Rombos)**: Para **demostraciones encadenadas paso a paso**. Cada paso $A_i$ tiene su propio horario de repaso independiente según el algoritmo FSRS (para no perder tiempo en pasos obvios y enfocarte en los pasos difíciles), y al repasar el paso actual, los pasos anteriores ya demostrados ($A_1, \dots, A_{i-1}$) se muestran arriba como contexto verificado.
  - **Cloze Holístico (Elipses)**: Para teoremas de equivalencia (*"Las siguientes afirmaciones son equivalentes..."*) o sistemas de axiomas, donde todas las demás afirmaciones se muestran como contexto mutuo.
- ⚡ **MathJax 3 100% Offline**: Renderizado tipográfico ultra-rápido de fórmulas TeX/LaTeX complejas y diagramas conmutativos vectoriales SVG sin requerir conexión a internet.
- 🧠 **Motor FSRS-5**: Programación de intervalos basada en el algoritmo matemático *Free Spaced Repetition Scheduler* (FSRS v5) para garantizar una retención óptima en el menor tiempo.
- ↩️ **Deshacer Universal (`Ctrl+Z` / `Ctrl+Y`)**: Deshaz calificaciones de repaso erróneas o ediciones accidentales en el grafo con total tranquilidad.
- 📱 **Compañero Móvil Android (`morphism-portable`)**: Estudia donde quieras con la aplicación táctil para Android, sincronizando tus progresos mediante un código QR efímero en tu red local sin depender de la nube.
- 🎨 **10 Temas Integrados**: Interfaz adaptable a cualquier resolución (incluyendo portátiles desde 720p), con temas como *Catppuccin Mocha*, *Dracula*, *Tokyo Night*, *OLED Midnight*, *GitHub Light*, entre otros.

---

## 🚀 Inicio Rápido

### En el Escritorio (Windows, Linux, macOS)

**Requisitos**: Python 3.11 o superior.

1. Clona el repositorio e instala las dependencias del proyecto:
   ```bash
   pip install -e .
   ```
2. Inicia la aplicación:
   ```bash
   python run_morphism.py
   ```
   *(o ejecuta `morphism-srs` directamente si tu entorno añade scripts al PATH).*

---

### En Android (`morphism-portable`)

El repositorio incluye un compilador autónomo en Kotlin que descarga el toolchain necesario y construye el APK sin requerir Android Studio:

```bash
python src/morphism-portable/build_portable.py
```

El archivo resultante `morphism-srs.apk` se deposita en la raíz del repositorio. Para sincronizar:
1. Abre el diálogo **Móvil / QR** en la aplicación de escritorio (manteniendo ambos dispositivos en la misma red local Wi-Fi).
2. Escanea el código QR desde la app móvil.
3. Estudia sin conexión a internet y vuelve a sincronizar al regresar a casa para consolidar tus métricas.

---

## 📝 Ejemplo de Formato `.mdsl`

Crear contenido o configurar el *prompt* de un LLM para generar material es intuitivo:

```text
COURSE "Álgebra Abstracta"
FOLDER "Teoría de Grupos"

NEW NOTE "Definición de Grupo"
MODE standard
TAGS group_theory, definition

CARD 1 "Axiomas Formales"
FRONT
¿Cuál es la definición formal de un <b>grupo</b> $(G, \cdot)$?
BACK
Un conjunto $G$ con una operación binaria $\cdot : G \times G \to G$ que cumple:
<ul>
  <li><b>Asociatividad:</b> $(a \cdot b) \cdot c = a \cdot (b \cdot c)$</li>
  <li><b>Elemento neutro:</b> $\exists e \in G \text{ tal que } e \cdot a = a \cdot e = a$</li>
  <li><b>Inversos:</b> $\forall a \in G, \exists a^{-1} \in G \text{ tal que } a \cdot a^{-1} = a^{-1} \cdot a = e$</li>
</ul>

NEW NOTE "Unicidad del Elemento Neutro"
MODE serial
TAGS group_theory, proof, uniqueness

CARD 1 "Planteamiento"
FRONT
Si $e$ y $e'$ son ambos elementos neutros en un grupo $(G, \cdot)$, ¿cómo relacionamos ambos?
BACK
Evaluamos el producto $e \cdot e'$ de dos formas distintas usando el axioma de elemento neutro.

CARD 2 "Deducción Final"
FRONT
Evalúa $e \cdot e'$ usando primero que $e$ es neutro por la izquierda, y luego que $e'$ es neutro por la derecha.
BACK
Dado que $e$ es neutro por la izquierda: $e \cdot e' = e'$.<br>
Dado que $e'$ es neutro por la derecha: $e \cdot e' = e$.<br>
Por lo tanto, $e = e'$. $\blacksquare$

LINK "Definición de Grupo" -> "Unicidad del Elemento Neutro"
```

---

## 🏛️ Arquitectura Técnica y la Carpeta `specZ`

Para los desarrolladores, colaboradores o cualquier persona interesada en los detalles técnicos internos (arquitectura en cuatro capas, esquema SQLite v2, motor de sanitización de LaTeX, DOM incremental $O(1)$ o paridad FSRS-5 entre Python y Kotlin), **toda la especificación técnica completa se encuentra en la carpeta [`specZ/`](specZ/)**.

---

## 🤝 Créditos y Agradecimientos

- **[Anki](https://apps.ankiweb.net/) y [AnkiDroid](https://ankidroid.org/)**: Pioneros indiscutibles del software libre de repetición espaciada. Su ecosistema, sus protocolos de sincronización y su visión abrieron el camino a la memorización computarizada en todo el mundo y son la inspiración original de este proyecto.
- **SSParzival**: Crédito y agradecimiento especial por el desarrollo del fork **`Morphism-SRS-Plus`**, el cual introdujo la arquitectura móvil desarrollada en `morphism-portable`.
- **Comunidad de [Open Spaced Repetition (FSRS)](https://github.com/open-spaced-repetition)**: Por su investigación abierta y su moderno algoritmo de decaimiento de memoria FSRS v5.
- **MathJax Consortium**: Por posibilitar el renderizado tipográfico offline de LaTeX en aplicaciones modernas.

---

## 📄 Licencia

Este proyecto está publicado bajo la licencia **GNU General Public License v3.0 (GPL-3.0-or-later)**.  
Eres libre de usar, estudiar, modificar y distribuir este software. Consulta el archivo de licencia del repositorio para más información.
