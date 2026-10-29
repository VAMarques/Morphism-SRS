-C:\repos\Morphism SRS\Morphism nightly>python run_morphism.py

Se han encontrado los siguientes 3 errores.

js: MathJax: Invalid option "autoload" (no default value).



Traceback (most recent call last):
  File "C:\repos\Morphism SRS\Morphism nightly\src\morphism_srs\ui\views\explorer_view.py", line 1207, in _on_canvas_context_menu
    self._on_bulk_delete()
    ~~~~~~~~~~~~~~~~~~~~^^
  File "C:\repos\Morphism SRS\Morphism nightly\src\morphism_srs\ui\views\explorer_view.py", line 1150, in _on_bulk_delete
    self.explorer_controller.note_repo.unlink_from_course(self.current_course_id, nid)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\repos\Morphism SRS\Morphism nightly\src\morphism_srs\storage\repositories\note_repo.py", line 278, in unlink_from_course
    self.conn.execute("UPDATE notes SET course_id = ? WHERE id = ?;", (new_cid, note_id))
    ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
sqlite3.IntegrityError: NOT NULL constraint failed: notes.course_id



  File "C:\repos\Morphism SRS\Morphism nightly\src\morphism_srs\ui\views\explorer_view.py", line 864, in _on_selection_changed
    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, it.isSelected() and not self.hand_pan_mode)
                                                             ~~~~~~~~~~~~~^^
RuntimeError: Internal C++ object (GraphNodeItem) already deleted.


Esto previene en parte el poder borrar notas en masa, el otro error, previene el poder mover una nota en modo "Pan".



- Courses deberia tener UUID? Folders no, una folder es organizaciónal, una Course es unica y tener el mismo nombre no implica ser la misma Course, tener distinto nombre no implica ser "distinta". Por otra parte las carpetas al ser organizacionales, si deben tener nombre unico. (En ingles/español, el mismo curso puede cambiar de nombre, pero las carpetas no tendrian por que ser unicas).

¿No se tiene soporte para Folders en .mdsl? De hecho si, revise y si hay, pero no estoy seguro que la implementación sea adecuada, actualmente:

COURSE "Group Theory Foundations"
FOLDER "Pure Mathematics/Algebra"

seria el formato usado. Con Courses con UUID deberiamos tener algo mas como:

COURSE "Group Theory Foundations" UUID {uuid} FOLDER "Pure Mathematics"/"Algebra"

o (sin UUID)

COURSE "Group Theory Foundations" FOLDER "Pure Mathematics"/"Algebra"

o (sin carpeta)

COURSE "Group Theory Foundations" UUID {uuid}

o (sin ninguno)

COURSE "Group Theory Foundations"


lo cual es mas claro, ademas nota como FOLDER debe tener las comillas fuera de "/", la razon es que el caracter / *podria* confundirse con el nombre de una carpeta, ademas que no habria restricción con usarlo fuera de las comillas. Ademas esta sintasis es mas directa

- El escaner QR (portable) tiene una relación de aspecto incomoda, la camara del telefono deberia verse en aspecto 1:1 cuando se trata de escanear.

- Los nodos en la versión portable todavia no se ajustan bien. Los enlaces no se ajustan automaticamente. (los puntos de unión deberian ser los puntos mas cercanos de unión, no necesariaamente los puntos cardinales) Ademas no me gusta que al estudiar me tire a la primera nota. Yo quiero estudiar el nodo en que le hago click, no necesariamente el primero en el DAG (eso tambien debe corregirse en escritorio, la advertencia debe darse solo en notas donde el prerequisito nunca se haya completado, es decir, que tengan todavia notas en new. Eso tambien implica que una nota debe considerarse "Gris" cuando tiene al menos una carta en estado "new" o "learning" (estudio incompleto), y una nota gris, sin prerequisitos grises, no lanza advertencia, una nota gris con prerequisitos grises si lanzaria advertencia. Si esta due o relearning (despues de again) entonces eso si se permitiria)

- Mas generalmente el estudio por DAG de los repasos deberia ir en orden inverso, de arriba hacia abajo. (En teoria: Los nodos de arriba al estudiarlos 'estimulan' los de abajo)


¿Sistema de rachas/puntajes? (la denominación de mathacademy para el "puntaje" es XP), esto motivaria a uno a estudiar mas, SIN EMBARGO, las rachas deben estar desacopladas de las reviews, pues si por ejemplo borras mazos perderas tu racha, lo cual seria desmoralizante. Añade entonces el siguiente sistema:
- Las rachas son simplemente un valor entero que sube cada dia que entras, con un intervalo un poco mas amplio que un dia (18 horas desde la ultima vez que entraste, y 32 horas posterior a eso)
- La XP es un float (para eventualmente). Pero por ahora seria suficiente que aumente en 1.0XP cada review (Sin importar si es Again o good o easy)
Estos se mostraran en la ventana de estadisticas.


- Revisa specZ\PLAN_SVG_MASK_TINTING.md para cambiar los diagramas comutativos y añadir tests para ellos.