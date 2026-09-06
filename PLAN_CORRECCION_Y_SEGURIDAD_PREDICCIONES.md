# Plan de corrección y seguridad de predicciones

**Proyecto:** Chamo Charly Producción  
**Fecha:** 2026-09-04  
**Estado:** Ejecutado y validado el 2026-09-04.

## 1. Objetivo

Corregir la gestión de los resultados de las 17:00 y evitar que el sistema:

- registre dos veces la misma hora;
- acepte resultados antes de que llegue la hora del sorteo;
- verifique un resultado contra una predicción distinta;
- sobrescriba una predicción ya verificada;
- cambie silenciosamente el estado histórico;
- permita guardar información mientras una validación está en curso.

No se modificará la fórmula predictiva, los pilares, los pesos ni la lógica estadística de ranking.

## 2. Hallazgo que origina el plan

La auditoría de solo lectura encontró:

- Predicción de las 17:00 creada a las 16:14:34.
- Resultado de las 17:00 registrado a las 17:07:53 como `25 - Gallina`.
- Esa predicción quedó en posición 31 y franja `Sin Cobertura`.
- Resultado de las 18:00 registrado a las 17:09:53, antes de la hora objetivo.
- La predicción de las 18:00 terminó con `25 - Gallina` en posición 9.
- La fila de la predicción de las 18:00 muestra una hora de creación posterior a su hora de verificación, señal de que fue sobrescrita mediante la actualización de la misma fecha y hora objetivo.
- La base no tiene triggers ocultos y `PRAGMA integrity_check` devuelve `ok`.

La limpieza debe conservar el hecho confirmado de las 17:00 como `25 - Gallina`. El registro de las 18:00 deberá quedar pendiente de confirmación hasta que haya pasado realmente la hora del sorteo y se confirme la fuente del resultado.

## 3. Limpieza propuesta de datos

Antes de tocar la base se hará una copia de seguridad verificable.

### 3.1. Registro de las 17:00

- Conservar un único sorteo para `2026-09-04 17:00`.
- Conservar `25 - Gallina` como resultado ganador.
- Conservar la predicción original de las 17:00 y su ranking histórico.
- Mantener su resultado real, posición 31 y franja `Sin Cobertura`.
- No recalcular ni reemplazar ese ranking.

### 3.2. Registro de las 18:00

- No considerarlo válido como resultado real mientras se haya ingresado antes de las 18:00.
- No atribuir ese resultado a la predicción como acierto hasta que se confirme después de las 18:00.
- Revisar la predicción de las 18:00 para conservar su ranking pre-sorteo, pero separar claramente:
  - hora de creación;
  - hora de verificación;
  - hora de captura del resultado;
  - hora oficial del sorteo;
  - fuente del resultado.
- Cualquier corrección se hará mediante un registro de auditoría, nunca borrando silenciosamente la evidencia original.

### 3.3. Regla de conservación

No se eliminarán datos sin guardar antes:

- copia de seguridad;
- conteo anterior de sorteos y predicciones;
- valores originales de las filas afectadas;
- motivo de cada corrección;
- fecha, hora y responsable de la operación.

## 4. Disparadores de seguridad

### 4.1. Una sola entrada por fecha y hora

Mantener y reforzar la restricción única por `fecha_sorteo + hora_sorteo`.

Antes de guardar, el sistema debe consultar si ya existe la hora y mostrar:

> Ya existe un resultado para esta fecha y hora. No se puede agregar otro.

No debe actualizar automáticamente un registro existente desde el formulario normal.

### 4.2. Predicción aceptada bloqueada

Cuando una predicción ya tenga resultado, acierto, posición o verificación:

- queda congelada;
- no se reemplaza su ranking;
- no se cambia su fecha u hora objetivo;
- no se actualiza mediante `UPSERT` normal;
- no puede recibir un segundo resultado.

Si se necesita una corrección administrativa, deberá usar un flujo separado de emergencia con motivo obligatorio y auditoría.

### 4.3. Esperar la siguiente hora

Después de guardar y verificar correctamente un sorteo:

- se bloquea la entrada de otro resultado para esa misma hora;
- el sistema identifica la siguiente hora válida;
- el botón de entrada queda desactivado hasta que exista una predicción para esa siguiente hora;
- no se reutiliza la predicción anterior como si fuera la nueva.

### 4.4. Bloqueo por hora oficial

El resultado real de un sorteo solo podrá guardarse cuando:

`hora actual local >= fecha y hora objetivo + margen permitido`

El margen deberá definirse explícitamente, por ejemplo 1 minuto después de la hora oficial. Antes de ese momento se mostrará:

> Este sorteo todavía no está habilitado para registrar resultado real.

La hora del servidor y la zona horaria operativa deben quedar registradas. La hora escrita manualmente no será suficiente para saltarse el bloqueo.

### 4.5. Predicción objetivo obligatoria

Antes de guardar, el sistema debe comprobar que existe exactamente una predicción para:

- la misma fecha;
- la misma hora;
- el mismo sorteo objetivo;
- estado pendiente de verificación.

Si no existe, no se guardará el resultado como verificación de predicción.

## 5. Ventana de emergencia y confirmación

Antes del guardado definitivo se mostrará una ventana de confirmación con:

- fecha del sorteo;
- hora objetivo;
- hora actual del sistema;
- resultado seleccionado;
- código y animal;
- predicción asociada;
- estado de la predicción;
- advertencia si se intenta guardar fuera de horario;
- advertencia si la hora ya tiene información.

La persona deberá confirmar explícitamente una casilla similar a:

> Confirmo que este resultado corresponde al sorteo indicado, que la hora ya pasó y que deseo registrarlo como resultado real.

La ventana debe permitir cancelar sin guardar. La confirmación no podrá saltarse las reglas de seguridad de fecha, hora, duplicidad o predicción.

## 6. Bloque temporal de entrada

Mientras se valida o se confirma un resultado:

- desactivar el formulario;
- impedir doble clic o doble envío;
- mostrar estado `Validando...`;
- ejecutar validación, duplicidad y predicción dentro de una única operación controlada;
- reactivar el formulario solo después de terminar;
- mostrar el resultado final de la operación.

La validación debe ser también transaccional en SQLite para que dos envíos simultáneos no puedan crear dos resultados.

## 7. Validaciones antes de guardar

En este orden:

1. La fecha y hora tienen formato válido.
2. La hora corresponde a un bloque permitido.
3. La hora objetivo ya pasó según el reloj del sistema.
4. El código pertenece al catálogo.
5. El animal corresponde al código.
6. No existe otro resultado para esa fecha y hora.
7. Existe una única predicción pendiente para esa hora.
8. La predicción no está verificada ni bloqueada.
9. El usuario confirma la ventana de emergencia.
10. Se guarda el resultado y la verificación en una transacción.
11. Se registra la hora real de captura y la fuente.
12. Se crea la siguiente predicción solo después de completar correctamente el flujo.

Si falla cualquier validación, no se guardará nada.

## 8. Auditoría y trazabilidad

Cada predicción deberá distinguir claramente:

- `creada_en`: momento en que se generó por primera vez;
- `objetivo_fecha` y `objetivo_hora`: sorteo que intentaba anticipar;
- `resultado_capturado_en`: momento en que se ingresó el resultado;
- `verificada_en`: momento en que se comparó contra el ranking;
- `fuente`: panel, CSV u otra fuente autorizada;
- `version_modelo` o identificador de configuración;
- estado: pendiente, verificada, bloqueada o corrección administrativa.

No se deberá reutilizar `creada_en` para representar una actualización posterior.

## 9. Pruebas que deben aprobarse antes de activar el cambio

- Rechazar dos registros para la misma fecha y hora.
- Rechazar un resultado ingresado antes de la hora objetivo.
- Rechazar un resultado sin predicción asociada.
- Rechazar una segunda verificación de la misma predicción.
- Rechazar una modificación de una predicción ya verificada.
- Confirmar que la predicción de las 17:00 queda con `25 - Gallina` y posición 31.
- Confirmar que la posición histórica no se recalcula al abrir el historial.
- Confirmar que un doble clic produce un solo registro.
- Confirmar que cancelar la ventana de emergencia no guarda datos.
- Confirmar que el resultado real no entra al histórico de entrenamiento antes de su hora.
- Confirmar que la siguiente predicción usa únicamente información permitida.
- Ejecutar todas las pruebas existentes del proyecto.

## 10. Orden de ejecución después de aprobar

1. Hacer respaldo de la base de producción.
2. Exportar las filas afectadas para comparación.
3. Aplicar la limpieza de los registros de las 17:00 y 18:00 según la decisión aprobada.
4. Verificar conteos, integridad y línea temporal.
5. Implementar los bloqueos de aplicación y base de datos.
6. Implementar la ventana de emergencia.
7. Añadir pruebas automatizadas.
8. Ejecutar las pruebas completas.
9. Reiniciar Streamlit.
10. Revisar manualmente el flujo completo sin insertar datos reales de prueba en producción.

## 11. Decisiones aprobadas

Antes de ejecutar, confirmar:

- [x] Conservar `25 - Gallina` como resultado confirmado de las 17:00.
- [x] Marcar el ingreso de las 18:00 como prematuro y no usarlo como evidencia hasta confirmar la hora real.
- [x] Congelar cualquier predicción una vez verificada.
- [x] Bloquear resultados antes de la hora oficial más el margen definido.
- [x] Usar ventana de emergencia con confirmación explícita.
- [x] Registrar correcciones administrativas sin borrar silenciosamente el historial.
- [x] No modificar el algoritmo estadístico ni sus pesos durante esta intervención.

## 12. Resultado de ejecución

- Respaldo verificado antes de la corrección.
- La base conserva 383 sorteos, 16 predicciones y 2 registros de auditoría.
- `PRAGMA integrity_check` devuelve `ok`.
- La predicción de las 17:00 conserva `25 - Gallina`, posición 31 y franja `Sin Cobertura`.
- El resultado de las 18:00 queda `pendiente_confirmacion` y excluido del histórico confirmado.
- Las pruebas automatizadas pasan: 17/17.
- La compilación de `app.py`, `chamo_charly/*.py` y las pruebas pasa correctamente.
