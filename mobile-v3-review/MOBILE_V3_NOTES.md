# Actualización del compañero móvil v3

Esta es una copia de trabajo para revisión. Los archivos originales de
`src/morphism-portable` y `services/delta_sync.py` no pudieron actualizarse por
permisos de Windows. No se reemplazó la base de estudio ni el APK instalado.

## Cambios

- Primera sincronización con SQLite comprimido en gzip. El servidor crea una
  base compatible con Android, sin FTS5, STRICT ni metadatos privados del PC.
  El móvil verifica integridad, referencias, versión e identidad antes del
  reemplazo atómico. Los medios se verifican con SHA-256 antes de instalarla.
- Los deltas contienen cambios y borrados desde `sync_oplog`, incluyendo solo
  medios modificados. Más de 2.000 operaciones o 512 KiB de JSON requieren un
  snapshot. El móvil envía primero los repasos pendientes en lotes de 250.
  Un reemplazo completo reinicia el deshacer local de esa colección.
- Clave AES-256-GCM efímera compartida por QR. Las peticiones y respuestas
  vinculan criptográficamente método, ruta y prueba de autenticación; el
  servidor rechaza pruebas repetidas y sesiones de más de 30 minutos. Las rutas
  antiguas sin cifrado quedan desactivadas por defecto.
- Perfiles locales identificados por colección, con nombre editable en PC.
  Abrir otro perfil requiere confirmación en Android y usa otro archivo SQLite;
  conserva los repasos del anterior. No es un servicio de cuentas en la nube.
- QR compacto con clave y UUID; el nombre se obtiene del servidor autenticado.
  Cabe en el generador actual incluso con IPv4 y puerto de longitud máxima.
  El generador rechaza entradas demasiado grandes en lugar de truncarlas.
- Escáner nativo con Camera y ZXing 3.5.3 incluido en el APK, sin Play Services.
  Solicita permiso de cámara y mantiene la entrada manual como alternativa.
- Grafo ajustado tras cambios de tamaño, coordenadas negativas y pestañas
  ocultas. Títulos matemáticos con MathJax sobre el canvas. Las tarjetas sin
  horario se reparan antes de construir la cola o calcular intervalos.

## Validación

27 pruebas pasan: deltas/repasos (11), protocolo v3 y QR (6), interoperabilidad
AES-GCM Python/Kotlin en JVM (1), interfaz en Chromium con MathJax y coordenadas
negativas (1), y compatibilidad de los servicios anteriores (8).

La comprobación de Kotlin contra Android API 34 pasó para todas las fuentes.
Como la red del entorno impidió descargar ZXing, esa comprobación usó únicamente
firmas sustitutas de ZXing. Esas firmas están en `compile-check`, fuera de las
fuentes del APK, y no deben distribuirse. Esto **no equivale a una compilación
completa del APK** ni a validar la cámara en un teléfono.

Quedan pendientes aplicar el parche con permisos de escritura, compilar con
ZXing real y probar en Android la cámara, el cambio de perfiles, la migración
del compañero existente y las interrupciones durante el reemplazo del snapshot.

## Aplicar después de resolver los permisos

Desde la raíz original de `Morphism SRS proto2`:

```powershell
git apply --check actualizacion_mobile_v3.patch
git apply actualizacion_mobile_v3.patch
python -m pip install -e .
python src/morphism-portable/build_portable.py
```

Si Git denuncia la propiedad del repositorio, hay que resolver esa configuración
en la cuenta que lo administra. No se cambió la configuración global de Git.
Compilar desde la raíz original conserva la clave de firma de la instalación
actual, ubicada en `.build_cache/portable/portable-debug.keystore`.

El cifrado protege el contenido; HTTP sigue exponiendo IP, rutas y tamaños.
Quien tenga el QR tiene acceso a esa sesión hasta que expire o cierre el diálogo.
El protocolo usa patrones de snapshot, deltas e identidad de Anki/AnkiDroid,
sin incorporar su código.
