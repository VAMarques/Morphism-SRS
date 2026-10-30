# Guía de Principios y Especificaciones para la Generación de Notas y Tarjetas SRS

Este documento establece los principios de diseño, especificaciones de formato y flujo de trabajo para generar archivos de importación JSON compatibles con el sistema de repetición espaciada (SRS). 

Cualquier usuario o agente de IA (como Antigravity, Claude, GPT, etc.) debe seguir esta guía para garantizar que las tarjetas generadas mantengan una estructura óptima, alta retención cognitiva y compatibilidad técnica perfecta.

---

## 1. El Formato JSON de Importación (Esquema Especificativo)

Los archivos de importación deben guardarse en la carpeta `to_import/` con formato `.json`. La estructura del archivo debe cumplir con el siguiente esquema de datos:

```json
{
  "notes": [
    {
      "title": "Título descriptivo de la nota",
      "tags": ["etiqueta1", "etiqueta2"],
      "note_type": "standard | serial_sequence_single",
      "desired_retention": 0.85,
      "cards": [
        {
          "type": "Flashcard",
          "title": "Título descriptivo de la tarjeta",
          "front": "Contenido del frente en HTML + MathJax",
          "back": "Contenido del reverso en HTML + MathJax"
        }
      ]
    }
  ],
  "edges": [
    {
      "source_id": "0",
      "target_id": "1",
      "label": "Prerequisite"
    }
  ]
}
```

### Descripción de Campos Principales

- **`notes`**: Lista de objetos de nota.
  - **`title`**: Título breve pero informativo del tema o teorema.
  - **`tags`**: Lista de cadenas para categorización (`"analisis"`, `"electromagnetismo"`, `"ch1"`, etc.).
  - **`note_type`**: 
    - `"standard"`: Para notas de definiciones o conceptos independientes.
    - `"serial_sequence_single"`: Para secuencias de pasos encadenados (demostraciones de teoremas o problemas por etapas).
  - **`desired_retention`**: Flotante entre $0.80$ y $0.90$ (por defecto `0.85`).
  - **`cards`**: Lista de tarjetas asociadas a la nota.
    - **`type`**: Siempre `"Flashcard"`.
    - **`title`**: Nombre del paso o concepto abordado en la tarjeta.
    - **`front`**: Pregunta o enunciado (formato HTML + MathJax).
    - **`back`**: Respuesta o desarrollo del paso (formato HTML + MathJax).
- **`edges`**: Lista opcional de conexiones dirigidas entre notas dentro de la misma importación. `source_id` y `target_id` corresponden a los índices basados en 0 de las notas en el arreglo `notes`.

---

## 2. Separación entre Definiciones y Demostraciones

Como regla general por defecto, **las notas de definiciones y las notas de demostraciones o resoluciones de problemas deben estar en archivos JSON separados**.

| Tipo de Contenido | Archivo JSON de Destino | Tipo de Nota (`note_type`) | Estructura Interna |
| :--- | :--- | :--- | :--- |
| **Definiciones y Conceptos** | `..._definitions.json` | `"standard"` | 1 Nota por Tema con **Múltiples Tarjetas** (1 tarjeta por definición individual). |
| **Demostraciones y Problemas** | `..._proofs.json` | `"serial_sequence_single"` | 1 Nota por Teorema/Problema con **Pasos Secuenciales Encadenados**. |

### 2.1 Regla para Notas de Definición (`standard` multi-tarjeta)
Cuando varias definiciones o conceptos "van juntos" (por ejemplo, los conceptos de *Abierto, Cerrado, Punto Límite, Punto Interior y Compacto* en topología):

- ❌ **NO hacer**: Crear una sola nota con una única tarjeta gigantesca que amontone todas las definiciones juntas.
- ❌ **NO hacer**: Crear 10 notas `standard` separadas con 1 sola tarjeta cada una si pertenecen al mismo tema unificado.
- ✔️ **HACER CORRECTAMENTE**: Crear **una sola nota `standard`** que contenga en su arreglo `"cards"` **múltiples tarjetas independientes** (una tarjeta enfocada por cada definición o subconcepto).

---

## 3. Razón y Fundamento Teórico de `serial_sequence_single`

Las demostraciones matemáticas complejas y los problemas sintácticos/físicos no deben meterse enteros en una sola tarjeta. Para esto se utiliza el tipo de nota `"serial_sequence_single"`.

### 3.1 Fundamento Probabilístico y Cognitivo
En teoría de la probabilidad, la probabilidad de recordar con éxito una cadena de $n$ pasos deductivos sera por probabilidad condicional:

$$P(A_1, A_2, A_3, \dots, A_n) = P(A_1) \cdot P(A_2 \mid A_1) \cdot P(A_3 \mid A_1, A_2) \cdots P(A_n \mid A_1, \dots, A_{n-1})$$

Si intentamos memorizar el bloque entero $P(A_1, \dots, A_n)$ en una sola tarjeta:
1. La probabilidad de recordar la tarjeta completa cae exponencialmente con el número de pasos.
2. El algoritmo SRS no puede saber qué paso específico se olvidó ($A_2$ vs $A_{n-1}$).
3. La carga cognitiva por tarjeta se vuelve paralizante.

### 3.2 Cómo Descomponer con `serial_sequence_single`
Al usar `serial_sequence_single`, dividimos la nota en una secuencia ordenada de tarjetas (pasos):

- **Paso 1 ($A_1$)**: Configuración inicial, hipótesis, truco clave o primer lema auxiliar.
- **Paso 2 ($A_2 \mid A_1$)**: Construcción intermedia o primera cota usando los resultados de $A_1$.
- **Paso 3 ($A_3 \mid A_1, A_2$)**: Paso de paso al límite, contradicción o evaluación.
- **Paso $n$ ($A_n \mid \dots$)**: Conclusión del teorema o evaluación en la frontera.

---

## 4. Flujo de Trabajo mediante Scripts en Python (`.py`)

### 4.1 ¿Por qué NO escribir archivos JSON crudos a mano?
En matemáticas y física, el uso intensivo de $\LaTeX$ implica un número masivo de barras invertidas (`\mathbb`, `\frac`, `\alpha`, `\partial`, `\sum`, `\int`). 

Si una IA o humano escribe el archivo `.json` directamente:
- Se producen frecuentemente errores de escape (e.g. `\f` se interpreta como *formfeed*, `\b` como *backspace*, `\n` como *newline*).
- Las comillas dobles y corchetes dentro de fórmulas causan fallos de sintaxis en el intérprete de JSON.

### 4.2 Protocolo Obligatorio de Generación mediante Python
Toda generación de notas debe realizarse mediante un script auxiliar en Python guardado en `scratch/build_...py`:

1. Escribir los textos en Python utilizando **cadenas de texto crudas (raw string literals)** `r"..."`.
2. Estructurar el diccionario de Python respetando el esquema JSON.
3. Exportar el archivo mediante `json.dump(data, f, indent=2, ensure_ascii=False)`.
4. Validar automáticamente al final del script mediante `json.load(f)`.

*Ejemplo de código Python en `scratch/`:*

```python
import json
import os

os.makedirs("to_import", exist_ok=True)

data = {
    "notes": [
        {
            "title": "Nombre del Teorema",
            "tags": ["analisis", "ch1"],
            "note_type": "serial_sequence_single",
            "desired_retention": 0.85,
            "cards": [
                {
                    "type": "Flashcard",
                    "title": "Paso 1: Planteamiento",
                    "front": r"<strong>Enunciado:</strong> Sea $f \in L^1(\mathbb R^d)$...",
                    "back": r"<strong>Demostración:</strong> Por la desigualdad $\int |f| < \infty$..."
                }
            ],
        }
    ],
    "edges": [],
}

target_path = os.path.join("to_import", "mi_archivo.json")
with open(target_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# Validación
with open(target_path, "r", encoding="utf-8") as f:
    json.load(f)
```

---

## 5. Formato de Contenido: MathJax, HTML y Selección de Ejemplos

### 5.1 MathJax / LaTeX
- Usar `$...$` para fórmulas integradas en el texto (inline math).
- Usar `$$...$$` para ecuaciones centradas en bloque (display math).
- Evitar sintaxis propia de Anki como clozes `{{c1::...}}` dentro de las secuencias estructuradas.

### 5.2 Formato HTML
El contenido de `front` y `back` se renderiza como HTML. Se recomienda utilizar etiquetas estándar para máxima legibilidad:
- `<strong>` para destacar conceptos o títulos de pasos.
- `<ul>` / `<ol>` y `<li>` para listas de hipótesis o propiedades.
- `<hr>` para separar el enunciado del paso práctico.
- `<p>` para párrafos explicativos.

### 5.3 Filosofía sobre los Ejemplos
- **Por defecto, NO incluir ejemplos triviales o extensos** en las notas teóricas a menos que el usuario los solicite explícitamente.
- Concentrarse en la rigor de los enunciados, las definiciones formales y la estructura lógica de las demostraciones.

---

*Cualquier agente de IA o usuario que genere nuevos archivos JSON de importación debe adherirse a esta especificación para garantizar la coherencia del repositorio.*
