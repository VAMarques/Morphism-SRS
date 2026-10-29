# Plan de Acción: Tintado y Renderizado de Diagramas SVG Monocromáticos vía CSS Mask

> **Estado**: Propuesta / Plan de Acción  
> **Objetivo**: Reemplazar la técnica de inversión cromática (`filter: invert(...) hue-rotate(...)`) descrita en `01_ARCHITECTURE_AND_PROJECT_STRUCTURE.md` (§3.3) por una estrategia de **máscara alfa CSS (`mask-image`)** para diagramas vectoriales SVG monocromáticos (TikZ, Quiver, etc.).  
> **Ámbito**: Motor WebEngine (`cards.css`, renderizado de plantillas HTML de tarjetas en revisión y previsualización).

---

## 1. Motivación y Diagnóstico

En la especificación actual (`01_ARCHITECTURE_AND_PROJECT_STRUCTURE.md`, §3.3):
```css
/* Especificación actual */
.commutative-diagram.invert-on-dark {
    filter: invert(0.92) hue-rotate(180deg);
}
```

### Problemas identificados con `filter`:
1. **Inconsistencia cromática con el tema**: Un filtro genérico de inversión produce tonalidades blancuzcas o grisáceas arbitrarias según el fondo, que no coinciden con la variable de color del texto principal del tema (`var(--theme-text-color)` o `--text-fg`).
2. **Degradación en rasterización**: Los filtros CSS sobre etiquetas `<img>` a menudo provocan que el motor de renderizado rasterice la imagen antes de aplicar el filtro en la GPU, perdiendo nitidez en los trazos finos de flechas y tipografía de Quiver/TikZ.
3. **Complejidad innecesaria de alternativas inline**: Incrustar el XML completo del SVG en el DOM para manipular nodos con `currentColor` expone el render a fallos si el SVG contiene definiciones complejas o incompatibles exportadas desde LaTeX.
4. **Enfoque de diseño**: Para diagramas conmutativos que usan colores explícitos en nodos/flechas, una imagen rasterizada/vectorial estándar sin tintar es suficiente. Los diagramas matemáticos estructurales normales son típicamente monocromáticos (trazos y etiquetas en tinta negra sobre fondo transparente) y deben comportarse exactamente como "tinta tipográfica".

---

## 2. Solución Técnica Propuesta: `CSS mask-image`

La propiedad CSS `mask-image` (y su contraparte prefijada `-webkit-mask-image` para compatibilidad en Chromium / QWebEngine) utiliza el canal alfa del archivo SVG como máscara de recorte sobre el `background-color` del elemento contenedor.

### Mecánica Fundamental
1. El archivo `.svg` se carga como máscara sobre un elemento `<span>` o `<div>`.
2. El fondo (`background-color`) se define con la variable CSS de texto activa: `var(--theme-text-color)`.
3. Todo trazo o texto del SVG se "pinta" instantáneamente y de forma homogénea con el color exacto del texto del tema actual, tanto en modo claro, oscuro, sepia o temas de alto contraste.

---

## 3. Especificación del Marcado y Estilos

### 3.1 Estilos CSS (`src/morphism_srs/resources/web/css/cards.css`)

```css
/* Contenedor del diagrama monocromático con máscara */
.diagram-mask-container {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 1.2em auto;
    max-width: 100%;
}

/* Elemento vector tintado */
.commutative-diagram-mask {
    display: inline-block;
    background-color: var(--theme-text-color, #1a1a1a);
    
    /* Configuración de la máscara vectorial */
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    
    /* Dimensiones responsivas por defecto (ajustables vía atributos/inline) */
    width: 100%;
    min-height: 120px;
    max-height: 450px;
    
    /* Transición suave al alternar temas */
    transition: background-color 0.15s ease-in-out;
}
```

### 3.2 Marcado HTML Generado en la Tarjeta

Cuando se procesa una tarjeta que referencia un diagrama conmutativo SVG almacenado en `MediaVault`:

```html
<div class="diagram-mask-container">
    <div 
        class="commutative-diagram-mask" 
        style="-webkit-mask-image: url('morphism://media/<sha256>.svg'); mask-image: url('morphism://media/<sha256>.svg'); width: 320px; height: 180px;"
        role="img"
        aria-label="Diagrama conmutativo">
    </div>
</div>
```

*(Nota: Las dimensiones `width` y `height` opcionales pueden inferirse de los atributos `viewBox` / `width` / `height` originales del SVG sanitizado por `MediaVault` o definirse mediante clases auxiliares).*

---

## 4. Matriz de Coexistencia de Medios

Para preservar la flexibilidad del usuario:

| Tipo de Contenido | Marcado HTML Utilizado | Tratamiento Visual |
| :--- | :--- | :--- |
| **Diagrama Conmutativo SVG Monocromático** (Quiver, TikZ estándar) | `<div class="commutative-diagram-mask" style="mask-image: url('morphism://media/...svg');"></div>` | Se pinta automáticamente con `var(--theme-text-color)`. Cero distorsión cromática. |
| **Diagrama con Colores Explícitos / Gráficos Complejos** | `<img src="morphism://media/...svg" class="raw-diagram" />` | Se muestra con sus colores nativos originales sin alteración ni máscaras. |
| **Imágenes Bitmap** (`.png`, `.jpg`, `.webp`) | `<img src="morphism://media/...png" />` | Render estándar sin filtros destructivos. |

---

## 5. Fases del Plan de Implementación

### Fase 1: Actualización de Hoja de Estilos (`cards.css`)
- [ ] Incorporar las clases `.diagram-mask-container` y `.commutative-diagram-mask` con fallback a color de texto estándar si la variable CSS no estuviera declarada.
- [ ] Asegurar soporte para propiedades estándar (`mask-*`) y de WebKit (`-webkit-mask-*`) para compatibilidad completa en `QWebEngineView`.

### Fase 2: Inserción y Parser en el Editor
- [ ] Al detectar la inserción de un archivo `.svg` (vía portapapeles o selector de archivos), el editor de tarjetas puede etiquetarlo por defecto como diagrama monocromático conmutable (`mask`), ofreciendo un selector o checkbox simple: *"Tintar según el tema (Monocromático)"* (activado por defecto para diagramas conmutativos).
- [ ] Si el usuario desmarca la opción (porque el diagrama incluye colores semánticos propios), se inserta como `<img>` estándar.

### Fase 3: Pruebas de Calidad Visual
- [ ] Probar diagramas exportados desde Quiver (`q.uiver.app`) con fondos transparentes.
- [ ] Alternar dinámicamente entre temas claro y oscuro para verificar que los glifos matemáticos de MathJax y los trazos del SVG adopten exactamente el mismo valor RGB hexadecimal.
- [ ] Confirmar que el consumo de GPU/CPU en `QWebEngineView` se mantiene bajo y sin artefactos de renderizado.

---

## 6. Plan de Verificación: Archivos de Test y Muestra .mdsl

Dado que actualmente no existe un entorno directo para validar visual ni unitariamente esta característica, se requiere crear artefactos de prueba específicos:

### 6.1 Suite de Pruebas Unitarias (`tests/test_svg_mask_rendering.py`)
Se debe crear un archivo de pruebas automatizadas con `pytest` que cubra:
1. **Sanitización e ingesta de SVG**:
   - Verificar que `MediaVault.store_media_bytes(...)` almacene correctamente un archivo SVG monocromático y extraiga o mantenga sus dimensiones/viewBox.
2. **Generación de marcado HTML**:
   - Comprobar que el compilador/transformador genere la estructura `<div class="commutative-diagram-mask" ...>` en lugar del `<img class="invert-on-dark" ...>` heredado cuando el recurso está marcado para tintado por máscara.
3. **Validación de reglas en `cards.css`**:
   - Test que parsea o comprueba la presencia de las declaraciones `-webkit-mask-image`, `mask-image`, `mask-size: contain` y `background-color: var(--theme-text-color)` en el archivo CSS entregado a `QWebEngineView`.

### 6.2 Deck de Ejemplo para Importación (`to_import/svg_mask_test_deck.mdsl`)
Un archivo `.mdsl` de muestra reproducible con un diagrama conmutativo real (ej. el Lema de los Cinco o un cuadrado conmutativo simple de categorías) embebido o referenciado, para verificar en la UI interactiva:

```text
COURSE "Pruebas de Renderizado Vectorial"
FOLDER "Categorías y Diagramas"

NEW NOTE "Propiedad Universal del Producto"
MODE standard
TAGS #test #svg #categories
CARD 1 "Diagrama Conmutativo del Producto"
FRONT
Dado dos objetos $X_1, X_2$, sea $P = X_1 \times X_2$ con proyecciones $\pi_1, \pi_2$.
Para cualquier objeto $Y$ con morfismos $f_1: Y \to X_1$ y $f_2: Y \to X_2$:

<div class="diagram-mask-container">
    <div class="commutative-diagram-mask" style="-webkit-mask-image: url('morphism://media/test_product_diagram.svg'); mask-image: url('morphism://media/test_product_diagram.svg'); width: 280px; height: 180px;"></div>
</div>

¿Qué propiedad garantiza la existencia y unicidad del morfismo punteado?
BACK
Garantiza la existencia y unicidad de un único morfismo $\langle f_1, f_2 \rangle: Y \to X_1 \times X_2$ tal que:
$$\pi_1 \circ \langle f_1, f_2 \rangle = f_1 \quad \text{y} \quad \pi_2 \circ \langle f_1, f_2 \rangle = f_2$$
```

Este archivo permitirá tanto la prueba unitaria del importador `.mdsl` como la inspección visual en `review_renderer.js` al alternar entre temas claros y oscuros.

