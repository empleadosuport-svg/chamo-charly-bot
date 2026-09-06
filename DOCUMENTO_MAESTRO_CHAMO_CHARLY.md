# Documento Maestro: Chamo Charly

**Versión:** 1.0 — Especificación inicial aprobada para revisión
**Fecha:** 2026-09-03
**Estado:** Plano funcional y técnico, sin código de producción

## 1. Propósito

Chamo Charly será un sistema personal de registro, análisis estadístico y asistencia para los resultados publicados de Lotto Activo.
El sistema recibirá manualmente los resultados mediante un panel web local. Con esos datos calculará estimaciones, detectará comportamientos atípicos, comparará modelos y explicará por qué genera una selección de hasta 10 animales.

Chamo Charly no puede garantizar aciertos ni cambiar la probabilidad real de un sorteo independiente. Su función será medir evidencia, incertidumbre, rendimiento histórico y riesgo de forma transparente.

## 2. Alcance inicial

- Registrar los resultados de cada sorteo.
- Permitir entrada manual por el panel.
- Mantener un histórico consultable y corregible con auditoría.
- Generar predicciones únicamente cuando exista información suficiente.
- Mostrar hasta 10 animales ordenados por probabilidad estimada.
- Verificar cada predicción contra el resultado real.
- Medir el rendimiento global y el rendimiento de cada modelo.
- Detectar cambios de comportamiento en los datos.
- Explicar qué información utilizó cada predicción.
- Permitir configurar ventanas temporales y parámetros de análisis.

Queda fuera de la primera versión:

- Apuestas automáticas.
- Manipulación o acceso al software de Lotto Activo.
- Promesas de una probabilidad mínima de acierto.
- Uso de información privada o no autorizada.

## 3. Universo de resultados

La lista proporcionada contiene 38 valores:

| Código | Animal |
|---:|---|
| 00 | Ballena |
| 0 | Delfín |
| 1 | Carnero |
| 2 | Toro |
| 3 | Ciempiés |
| 4 | Alacrán |
| 5 | León |
| 6 | Rana |
| 7 | Perico |
| 8 | Ratón |
| 9 | Águila |
| 10 | Tigre |
| 11 | Gato |
| 12 | Caballo |
| 13 | Mono |
| 14 | Paloma |
| 15 | Zorro |
| 16 | Oso |
| 17 | Pavo |
| 18 | Burro |
| 19 | Chivo |
| 20 | Cochino |
| 21 | Gallo |
| 22 | Camello |
| 23 | Cebra |
| 24 | Iguana |
| 25 | Gallina |
| 26 | Vaca |
| 27 | Perro |
| 28 | Zamuro |
| 29 | Elefante |
| 30 | Caimán |
| 31 | Lapa |
| 32 | Ardilla |
| 33 | Pescado |
| 34 | Venado |
| 35 | Jirafa |
| 36 | Culebra |

`00` y `0` son resultados distintos: Ballena y Delfín.

## 4. Horario esperado

Se registrarán aproximadamente 11 o 12 sorteos diarios, desde las 8:00 o 9:00 a. m. hasta las 7:00 p. m., con una frecuencia aproximada de una hora.

Cada registro conservará la hora publicada y la zona horaria configurada. No se asumirá que la hora de ingreso al sistema es la hora del sorteo.

## 5. Principios del sistema

1. **Datos antes que opiniones:** las hipótesis se descubrirán a partir del histórico.
2. **Separación temporal:** ninguna predicción podrá usar resultados posteriores al sorteo que intenta anticipar.
3. **Validación fuera de muestra:** el rendimiento se medirá con predicciones hechas antes de conocer el resultado.
4. **Incertidumbre visible:** se mostrarán probabilidades estimadas, tamaño de muestra y nivel de confianza.
5. **Autonomía controlada:** el sistema podrá comparar modelos y ajustar pesos, pero registrará cada cambio.
6. **Reproducibilidad:** cada predicción guardará la versión del modelo, los parámetros y la ventana de datos utilizada.
7. **Gestión responsable:** el módulo Kelly será opcional y no recomendará arriesgar dinero cuando no exista ventaja demostrada.

## 6. Pilares matemáticos

Los pilares no tendrán todos la misma función. Algunos validan los datos, otros describen patrones y otros combinan resultados.

### 6.1. Validación y calidad

#### 1. Prueba de chi-cuadrado

Compara las frecuencias observadas con las frecuencias esperadas bajo un modelo uniforme. Se aplicará con correcciones por tamaño de muestra y multiplicidad de pruebas.

**Salida:** estadístico, p-valor, desviaciones por animal y alerta de uniformidad.

Un p-valor bajo no demuestra fraude. Solo indica que los datos son poco compatibles con el modelo uniforme elegido.

#### 2. Intervalos de confianza binomiales

Estiman el rango plausible de la frecuencia de cada animal. Evitan presentar una frecuencia pequeña como una certeza.

**Salida:** frecuencia observada, intervalo y tamaño de muestra.

#### 3. Pruebas de independencia y autocorrelación

Evalúan si el resultado anterior, la hora o el día aportan información sobre el siguiente resultado.

**Salida:** medidas de dependencia, significancia y estabilidad en el tiempo.

### 6.2. Tiempo y secuencias

#### 4. Cadenas de Markov

Calculan transiciones como `Tigre -> Caimán`. Se probarán órdenes simples y se aplicará suavizado cuando haya pocas observaciones.

Una transición frecuente no se considerará útil hasta comprobarla en datos posteriores y compararla con una línea base.

#### 5. Decaimiento exponencial

Da más peso a los sorteos recientes mediante un factor configurable. Permitirá comparar ventanas de 7, 14, 30, 90 días y todo el histórico.

**Objetivo:** adaptarse a posibles cambios sin borrar el histórico original.

#### 6. Análisis temporal por grupos

Se compararán franjas horarias, días de la semana, jornada y otras variables disponibles. Este análisis sirve para descubrir inversiones o diferencias que un promedio global puede ocultar, relacionadas con la paradoja de Simpson.

### 6.3. Rarezas y corrección de interpretaciones

#### 7. Regresión a la media

Se utilizará como advertencia contra la interpretación de rachas extremas. No obligará a bajar automáticamente la probabilidad de un animal, porque una racha no prueba que el siguiente resultado deba ser distinto.

#### 8. Prueba de rachas de Wald-Wolfowitz

Evalúa si una secuencia presenta demasiadas agrupaciones o alternancias frente a una referencia aleatoria.

**Salida:** tipo de comportamiento compatible con los datos, p-valor y periodo analizado.

#### 9. Distribución binomial y multinomial

Para sorteos independientes, se utilizará la distribución binomial para estudiar cuántas veces aparece un animal y la multinomial para estudiar el conjunto completo.

Estas distribuciones sustituyen a la hipergeométrica en el caso principal, porque los sorteos se tratan como eventos independientes con reemplazo.

#### 10. Coeficientes del Triángulo de Pascal

El Triángulo de Pascal aporta los coeficientes combinatorios de la distribución binomial. No será un predictor separado; se usará para calcular la probabilidad de frecuencias, repeticiones y ausencias.

#### 11. Análisis de colisiones o paradoja del cumpleaños

Compara las repeticiones observadas de pares o tríos con las repeticiones esperadas por combinatoria. Una repetición no demuestra por sí sola que exista un ciclo; deberá validarse en periodos posteriores.

### 6.4. Inferencia y combinación

#### 12. Teorema de Bayes

Actualiza una probabilidad previa con la evidencia observada. Se usarán priors conservadores para evitar que pocas observaciones cambien demasiado el resultado.

**Salida:** probabilidad posterior, intervalo de incertidumbre y evidencia utilizada.

#### 13. Comparación de modelos

Se compararán modelos sencillos y modelos con variables temporales o secuenciales. El sistema elegirá el modelo con mejor rendimiento validado, no el que mejor explique accidentalmente el pasado.

#### 14. Regresión logística multinomial

Se considerará cuando exista suficiente histórico. Combinará variables como hora, día, resultado anterior, frecuencia reciente y transiciones.

La salida será un ranking de probabilidades para los 38 animales. Las probabilidades deberán sumar aproximadamente 1.

#### 15. Criterio de Kelly

Será un módulo de gestión de riesgo, no de predicción. Solo podrá calcularse si se conoce el pago neto, la probabilidad estimada y una ventaja estadística validada.

Por defecto se utilizará Kelly fraccionado o recomendación de no arriesgar. Nunca se interpretará como garantía de ganancias.

## 7. Flujo de datos

1. El administrador registra un resultado.
2. El sistema valida fecha, hora, código y animal.
3. Se detectan duplicados o correcciones.
4. El registro se guarda junto con su fuente y hora de captura.
5. Se actualizan las métricas disponibles.
6. Se genera una predicción para el siguiente sorteo, si hay datos suficientes.
7. La predicción queda congelada y asociada a un sorteo objetivo.
8. Tras el resultado, el administrador verifica la predicción.
9. El sistema calcula acierto, cobertura del top 10 y calibración.
10. Los modelos y pesos se evalúan con datos nuevos.

## 8. Panel de administración

### 8.1. Dashboard

Mostrará:

- Último resultado confirmado.
- Próximo sorteo objetivo.
- Predicción vigente.
- Top 10 con probabilidades estimadas.
- Tamaño de la muestra utilizada.
- Precisión reciente y global.
- Cobertura del top 10.
- Estado del modelo: observación, aprendizaje o activo.
- Alertas estadísticas y cambios detectados.

### 8.2. Predicción y verificación

Mostrará:

- Fecha y hora en que se creó la predicción.
- Sorteo objetivo.
- Los 10 animales ordenados.
- Probabilidad de cada animal.
- Probabilidad acumulada del conjunto de 10.
- Intervalo o nivel de incertidumbre.
- Pilares que influyeron en el resultado.
- Datos usados y ventana temporal.
- Modelo y versión empleados.

Después del sorteo tendrá un formulario para:

- Indicar el animal real.
- Indicar el código real.
- Confirmar si el dato fue verificado.
- Registrar una corrección, si hubo un error de captura.

El acierto se calculará automáticamente: será verdadero si el resultado real pertenece al top 10 congelado de esa predicción.

### 8.3. Data Feeder

Incluirá:

- Registro manual de fecha, hora, código y animal.
- Carga masiva mediante CSV.
- Tabla de los últimos resultados.
- Búsqueda, filtros y paginación.
- Detección de duplicados.
- Corrección con historial de cambios.
- Exportación de datos.

### 8.4. Analytics Hub

Incluirá:

- Frecuencia por animal.
- Frecuencia por hora y día.
- Animales ausentes y rachas observadas.
- Matriz de transición de Markov.
- Prueba de rachas.
- Pruebas de uniformidad.
- Distribuciones binomial y multinomial.
- Repeticiones de pares y tríos.
- Detección de cambios de régimen.
- Rendimiento por modelo y por pilar.
- Calibración de probabilidades.
- Comparación contra una selección aleatoria de referencia.

### 8.5. Configuración

Permitirá configurar:

- Lista oficial de códigos y animales.
- Zona horaria.
- Horarios esperados.
- Ventana temporal.
- Factor de decaimiento.
- Umbrales de alerta.
- Frecuencia mínima para activar un modelo.
- Pesos automáticos y manuales.
- Cuota o pago neto, solo para el módulo de riesgo.
## 9. Base de datos conceptual

### 9.1. `animales`

Catálogo oficial de códigos y nombres.

Campos mínimos: `id`, `codigo`, `nombre`, `activo`.

### 9.2. `sorteos`

Resultados observados.

Campos mínimos: `id`, `fecha_sorteo`, `hora_sorteo`, `codigo`, `animal_id`, `fuente`, `capturado_en`, `verificado`, `observaciones`.

Restricción recomendada: no permitir dos registros para el mismo sorteo objetivo sin una corrección explícita.

### 9.3. `predicciones`

Predicciones congeladas antes del resultado.

Campos mínimos: `id`, `creada_en`, `sorteo_objetivo`, `top10_json`, `probabilidades_json`, `probabilidad_conjunto`, `modelo`, `version_modelo`, `ventana_usada`, `datos_usados`, `explicacion_json`, `resultado_real`, `acierto`, `verificada_en`.

### 9.4. `evaluaciones_modelos`

Rendimiento histórico de cada modelo.

Campos mínimos: `id`, `modelo`, `periodo`, `cantidad_predicciones`, `aciertos_top1`, `aciertos_top10`, `log_loss`, `brier_score`, `calibracion`, `creado_en`.

### 9.5. `configuracion`

Parámetros del sistema.

Campos mínimos: `id`, `parametro`, `valor`, `descripcion`, `actualizado_en`.

### 9.6. `eventos_auditoria`

Cambios y acciones importantes.

Campos mínimos: `id`, `tipo_evento`, `entidad`, `entidad_id`, `detalle_json`, `creado_en`.

## 10. Aprendizaje y autonomía controlada

Durante los primeros 14 días, Chamo Charly estará en modo observación y generará métricas descriptivas. No se considerarán concluyentes los patrones basados en pocas observaciones.

La autonomía funcionará así:

1. Calcula varios modelos.
2. Genera predicciones fuera de muestra.
3. Compara su rendimiento contra una línea base aleatoria.
4. Detecta si un modelo empeora.
5. Ajusta pesos dentro de límites configurados.
6. Guarda el motivo, la fecha y la versión del cambio.
7. Revierte a un modelo base si la mejora no se mantiene.

No se permitirán ajustes basados únicamente en una racha corta.

## 11. Validación y métricas

Se medirán como mínimo:

- Acierto del animal principal.
- Cobertura del top 5 y top 10.
- Log loss.
- Brier score.
- Calibración: si se declara 10%, debe ocurrir aproximadamente 10% de las veces en una muestra suficiente.
- Rendimiento por hora, día y ventana.
- Comparación con selección aleatoria.
- Rendimiento antes y después de cada cambio de modelo.

Las pruebas se harán con validación temporal o walk-forward: el modelo solo podrá aprender del pasado para predecir el futuro.

## 12. Mensajes del sistema

- **Datos insuficientes:** `Estoy recopilando información. Esta estimación tiene baja confianza.`
- **Sin ventaja detectable:** `Los datos no muestran una diferencia estable frente al azar.`
- **Resultado guardado:** `Resultado registrado y asociado al horario indicado.`
- **Duplicado:** `Ya existe un registro para ese sorteo. Confirma si deseas corregirlo.`
- **Predicción verificada:** `Resultado comparado con la predicción congelada.`
- **Cambio detectado:** `El comportamiento reciente difiere del histórico. Se redujo el peso de los datos antiguos.`
- **Riesgo:** `No se recomienda arriesgar capital: no hay ventaja validada o faltan datos de pago.`

## 13. Fases de implementación

### Fase 0: Confirmación del formato

- Confirmar los 38 códigos.
- Confirmar si `00` y `0` son distintos.
- Confirmar qué dato publica la fuente.
- Confirmar zona horaria y horarios.

### Fase 1: Registro confiable

- Crear SQLite.
- Crear catálogo de animales.
- Crear tabla de sorteos.
- Crear entrada manual en Streamlit.
- Añadir validaciones y auditoría.

### Fase 2: Observación estadística

- Registrar al menos 14 días.
- Añadir frecuencias, intervalos y rachas.
- Crear comparación contra la línea base uniforme.
- No activar modelos complejos prematuramente.

### Fase 3: Predicción y verificación

- Crear predicción congelada por sorteo objetivo.
- Mostrar top 10 y explicación.
- Registrar resultado real.
- Medir cobertura y calibración.

### Fase 4: Modelos temporales

- Añadir decaimiento exponencial.
- Añadir Markov.
- Añadir análisis por grupos.
- Evaluar con walk-forward.

### Fase 5: Modelos avanzados y selección

- Añadir Bayes con priors conservadores.
- Añadir modelos multinomiales si hay suficientes datos.
- Comparar modelos y ajustar pesos con control.
- Añadir detección de cambios de régimen.

### Fase 6: Analítica y riesgo

- Completar Analytics Hub.
- Añadir análisis de repeticiones.
- Añadir módulo Kelly solo con pagos confirmados.
- Generar informes exportables.

## 14. Criterios de aceptación

- Los códigos y animales se validan sin ambigüedad.
- Un resultado válido se guarda una sola vez, salvo corrección auditada.
- Un resultado inválido se rechaza con un mensaje comprensible.
- Cada predicción queda asociada a un sorteo futuro concreto.
- Las predicciones no usan datos posteriores al objetivo.
- El top 10 y sus probabilidades se guardan sin cambiar después del sorteo.
- La suma de probabilidades del universo es aproximadamente 1.
- La verificación calcula automáticamente el acierto.
- El panel explica datos, modelo, versión y factores utilizados.
- El rendimiento se compara con una línea base aleatoria.
- El sistema declara baja confianza cuando corresponda.
- La base de datos puede respaldarse y restaurarse.
- El ingreso y el cálculo inicial funcionan en menos de 5 segundos con el volumen esperado.

## 15. Decisiones pendientes antes de programar

1. Confirmar el significado exacto de `00` frente a `0`.
2. Confirmar si el resultado oficial incluye código, animal o ambos.
3. Confirmar el formato de fecha y zona horaria.
4. Definir el pago neto, si se implementará el módulo Kelly.
5. Elegir el nombre técnico del proyecto: `chamo-charly` u otro.
6. Confirmar si SQLite será suficiente para la primera instalación local.

## 16. Nota final

El objetivo de Chamo Charly será producir una evaluación honesta y comprobable del comportamiento observado. Una lista de 10 animales puede cubrir una parte del universo, pero no implica por sí sola una probabilidad alta de acierto. La única manera de saber si un modelo aporta valor es medirlo con predicciones congeladas, datos posteriores y comparación contra el azar.
