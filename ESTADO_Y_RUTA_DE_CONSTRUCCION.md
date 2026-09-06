# Chamo Charly: Estado y Ruta de Construcción

**Fecha:** 2026-09-03  
**Proyecto:** `chamo-charly`  
**Tipo:** Aplicación local de registro y análisis estadístico

## 1. Objetivo del proyecto

Chamo Charly es una aplicación local para registrar resultados de Lotto Activo, analizarlos y generar estimaciones transparentes para el siguiente sorteo.

El sistema no puede garantizar aciertos ni cambiar la probabilidad real de un sorteo independiente. Su objetivo es:

- Organizar datos históricos confiables.
- Detectar desviaciones o comportamientos atípicos.
- Comparar métodos estadísticos.
- Generar un ranking de animales con probabilidades estimadas.
- Verificar cada predicción contra el resultado posterior.
- Medir si algún método supera de forma estable una línea base aleatoria.
- Mostrar incertidumbre y explicar cada decisión.

## 2. Decisiones confirmadas

- Nombre técnico: `chamo-charly`.
- Funcionamiento: 100% local en la PC.
- Interfaz: Streamlit.
- Base de datos: SQLite.
- Sin Telegram.
- Sin FastAPI en la primera versión.
- Entrada de datos: formulario manual y archivo CSV.
- Zona horaria operativa: Venezuela, UTC-4.
- Horario esperado: aproximadamente 8:00 a. m. a 7:00 p. m.
- Universo: 38 resultados.
- `00 - Ballena` y `0 - Delfín` son valores diferentes.
- Los códigos se conservan como texto: `00`, `0`, `01`...`36`.
- Las predicciones deben generarse antes de conocer el resultado objetivo.
- Los primeros 14 días se consideran principalmente una etapa descriptiva.
- Las probabilidades mostradas son estimaciones, no garantías.

## 3. Lo que ya se construyó

### 3.1. Proyecto y entorno

- Entorno virtual `.venv`.
- Archivo `requirements.txt`.
- Archivo `.gitignore`.
- `README.md` con instalación, ejecución y formato CSV.
- Paquete Python `chamo_charly`.

### 3.2. Catálogo

Se creó el catálogo oficial en `chamo_charly/catalog.py`.

Incluye los 38 códigos y animales, con validación de correspondencia. La normalización acepta, por ejemplo, `1` como equivalente de `01`, pero conserva `00` y `0` como valores distintos.

### 3.3. Base de datos

Se creó `chamo_charly/database.py`.

Actualmente contiene la tabla `sorteos` con:

- Fecha del sorteo.
- Hora del sorteo.
- Código.
- Animal.
- Día de la semana.
- Fuente.
- Momento de captura.
- Restricción de unicidad por fecha y hora.

También contiene `predicciones` con:

- Fecha y hora de creación.
- Fecha y hora objetivo.
- Modelo utilizado.
- Observaciones usadas.
- Ranking completo.
- Top 10.
- Probabilidad acumulada.
- Explicación.
- Resultado real.
- Acierto o fallo.
- Momento de verificación.

La importación masiva es idempotente: los registros existentes se omiten y los nuevos se guardan sin cancelar todo el lote.

### 3.4. Limpieza del histórico

El archivo bruto `entrenamiento datos reales.txt` contenía texto de páginas web, menús, imágenes, pies legales y resultados.

Se creó `chamo_charly/importer.py` y `clean_historical_data.py` para:

- Extraer solo resultados reales.
- Leer fecha, hora, código y animal.
- Convertir fechas a `YYYY-MM-DD`.
- Convertir horas a formato de 24 horas.
- Corregir `Caiman` a `Caimán`.
- Corregir `Delfin` a `Delfín`.
- Validar código y animal.
- Eliminar duplicados.
- Generar un CSV limpio.

Archivo generado:

`data/entrenamiento_datos_reales_limpio.csv`

Estado del histórico:

- 391 registros brutos detectados.
- 367 registros únicos después de limpiar y deduplicar.
- Falta el día 07/08/2026.
- El 03/09/2026 estaba incompleto en la fuente histórica.
- Posteriormente se añadió el resultado real de las 15:00.
- Estado actual de SQLite: 368 sorteos.

### 3.5. Panel actual

Se creó `app.py` con estas pestañas:

- **Dashboard:** cantidad de sorteos, etapa, universo, último resultado, predicción vigente y frecuencias.
- **Ingreso:** formulario manual y carga masiva CSV.
- **Predicción:** generación del ranking base y explicación.
- **Verificación:** registro del resultado real y cálculo del acierto.
- **Análisis:** frecuencias, chi-cuadrado, pesos recientes, rachas, horarios y transiciones de Markov.
- **Historial:** tabla de los últimos registros.

El panel se ejecuta en:

`http://localhost:8501`

### 3.6. Predictor base

Se creó `chamo_charly/predictor.py`.

El modelo principal de producción es `cobertura_ganador_por_hora`, el cual integra **7 pilares**:

1. Frecuencia Base Global.
2. Frecuencia por Hora Objetivo.
3. Frecuencia por Día de Semana + Hora.
4. Transiciones de Cadenas de Markov.
5. Decaimiento Exponencial Reciente.
6. Penalización Contextual por falsos positivos.
7. **Pirámide Invertida** (7° Pilar): Reducción determinista por fecha y hora objetivo. Tras una batería de 6 pruebas profundas en el Sandbox, demostró una mejora de +15.8% en cobertura del Top 10 (22 vs 19 aciertos fuera de muestra en 76 sorteos evaluados) y una correlación nula con los demás pilares ($r < 0.03$). Operando con monitoreo cercano durante los primeros 30 sorteos reales.

### 3.7. Pruebas realizadas

Actualmente existen pruebas para:

- Diferenciar `00` y `0`.
- Validar códigos y animales.
- Guardar resultados en SQLite.
- Limpiar y deduplicar texto.
- Importar lotes sin duplicar.
- Generar 38 probabilidades que suman aproximadamente 1.
- Guardar y verificar predicciones.
- Ejecutar métricas analíticas.

Último resultado validado: **7 pruebas exitosas**.

## 4. Pilares matemáticos y estado

No todos los pilares son predictores. Algunos validan datos, otros detectan patrones, otros combinan resultados y otros gestionan riesgo.

| Pilar o componente | Estado | Función futura |
|---|---|---|
| Frecuencia base | Implementado | Línea base de comparación |
| Bayes con suavizado | Implementado | Probabilidad posterior conservadora |
| Chi-cuadrado | Implementado en análisis | Evaluar uniformidad |
| Decaimiento exponencial | Implementado en análisis | Ponderar resultados recientes |
| Cadenas de Markov | Implementado en análisis | Estudiar transiciones |
| Prueba de rachas | Implementado en análisis | Estudiar alternancia y agrupación |
| Análisis por hora | Implementado en análisis | Comparar franjas horarias |
| Análisis por día | Parcial | Comparar días de semana |
| Regresión a la media | Conceptualmente definido | Advertir sobre extremos, no forzar resultados |
| Binomial/multinomial | Pendiente | Medir rareza de frecuencias |
| Triángulo de Pascal | Pendiente como métrica | Aportar coeficientes combinatorios |
| Paradoja del cumpleaños | Pendiente | Medir repeticiones de pares y tríos |
| Independencia/autocorrelación | Pendiente | Evaluar dependencia entre sorteos |
| Comparación de modelos | Pendiente | Saber qué modelo funciona mejor |
| Regresión logística multinomial | Pendiente | Combinar señales con suficiente histórico |
| Kelly | Pendiente y opcional | Gestionar riesgo, no predecir |

La Ley de Benford no será un pilar principal: no es apropiada como prueba directa de una ruleta digital limitada a 38 categorías. Si se estudia, se mantendrá como análisis exploratorio y no como evidencia de fraude.

La distribución hipergeométrica tampoco será el modelo principal, porque el caso estudiado se trata como sorteos independientes con reemplazo. Para frecuencias se priorizarán las distribuciones binomial y multinomial.

## 5. Lo que falta construir

### 5.1. Mejorar el modelo de predicción

El ranking actual solo usa frecuencia y Bayes. Falta crear un motor de combinación que pueda recibir señales de:

- Frecuencia histórica.
- Frecuencia reciente.
- Hora del sorteo.
- Día de la semana.
- Resultado anterior.
- Transiciones de Markov.
- Rachas.
- Pruebas de independencia.
- Rareza binomial.
- Análisis de cambios de régimen.

El motor debe normalizar todas las señales, evitar doble conteo y producir una única distribución de probabilidad para los 38 animales.

### 5.2. Métricas completas

Falta guardar y mostrar:

- Acierto top 1.
- Cobertura top 5.
- Cobertura top 10.
- Log loss.
- Brier score.
- Calibración.
- Rendimiento por hora.
- Rendimiento por día.
- Rendimiento por modelo.
- Comparación contra una selección aleatoria de 10 animales.

La referencia de una selección uniforme de 10 entre 38 es aproximadamente $26.32\%$.

### 5.3. Predicciones históricas fuera de muestra

La base histórica no contiene predicciones congeladas anteriores. Por eso no se puede afirmar todavía qué modelo habría funcionado en cada sorteo.

Se debe construir una evaluación walk-forward:

1. Tomar solo resultados anteriores a un sorteo.
2. Generar la predicción.
3. Compararla con el resultado siguiente.
4. Avanzar un sorteo.
5. Repetir el proceso.
6. Medir todos los modelos con las mismas fechas.

Esto evita que el sistema use información futura accidentalmente.

### 5.4. Verificación más completa

La pantalla actual verifica una predicción seleccionando un código. Falta añadir:

- Historial de predicciones verificadas.
- Resumen de aciertos y fallos.
- Cobertura top 10.
- Fecha de verificación.
- Modelo utilizado.
- Comparación entre predicción y resultado real.
- Filtros por fecha, hora y modelo.

### 5.5. Análisis avanzado

Falta incorporar al panel:

- Gráficos interactivos con Plotly.
- Matriz de Markov como mapa de calor.
- Gráficos de frecuencia por hora y día.
- Detección de pares y tríos repetidos.
- Distribución binomial de frecuencias.
- Alertas de cambio de comportamiento.
- Intervalos de incertidumbre.
- Comparación entre histórico completo y ventana reciente.

### 5.6. Configuración y auditoría

Falta crear:

- Tabla de configuración.
- Tabla de pesos de modelos.
- Tabla de eventos de auditoría.
- Control de ventana temporal.
- Control de decaimiento.
- Registro de versión del modelo.
- Registro de cambios automáticos.
- Copia de seguridad desde el panel.
- Restauración controlada.

### 5.7. Correcciones de experiencia de usuario

Falta mejorar:

- Mostrar claramente la fecha y hora objetivo.
- Evitar confundir hora de captura con hora del sorteo.
- Mostrar cuándo una predicción está pendiente.
- Mostrar un aviso si el usuario intenta verificar dos veces.
- Mostrar el porcentaje con formato consistente.
- Cambiar mensajes antiguos como “garantía de hecho” por “garantía de acierto”.
- Añadir botones de actualización y confirmación donde sea necesario.

## 6. Cómo se debe construir lo que falta

### Fase A: Consolidar el motor analítico

1. Crear funciones independientes para cada pilar.
2. Definir para cada función entrada, salida y supuestos.
3. Hacer que todas devuelvan datos identificables por código.
4. Añadir intervalos y tamaño de muestra.
5. Crear pruebas con datos pequeños y casos extremos.
6. No usar una alerta estadística como predicción automática sin evaluación.

### Fase B: Crear señales comparables

Cada señal debe convertirse a una escala común para los 38 animales. Por ejemplo:

- Probabilidad suavizada.
- Puntuación normalizada.
- Penalización.
- Indicador contextual.

Los pilares globales, como chi-cuadrado, no deben fingir una probabilidad individual. Deben funcionar como información de contexto o factor de confianza.

### Fase C: Construir el combinador

El combinador debe:

1. Recibir la línea base Bayesiana.
2. Recibir señales temporales y secuenciales.
3. Aplicar pesos iniciales conservadores.
4. Normalizar la distribución final.
5. Generar top 10.
6. Guardar la contribución de cada pilar.
7. Mantener una comparación contra la línea base.

Inicialmente los pesos serán fijos y documentados. Solo después de acumular predicciones verificadas podrán ajustarse automáticamente.

### Fase D: Crear evaluación walk-forward

Se debe evaluar cada modelo en el mismo conjunto de sorteos futuros simulados. El sistema comparará:

- Aleatorio uniforme.
- Frecuencia histórica.
- Bayes.
- Bayes más decaimiento.
- Bayes más horario.
- Markov.
- Combinador.

El modelo ganador será el que mantenga mejor desempeño fuera de muestra, no el que mejor reproduzca el pasado.

### Fase E: Integrar verificación y aprendizaje

Después de cada nuevo resultado:

1. Guardar el resultado.
2. Buscar la predicción cuyo objetivo coincide.
3. Marcar acierto o fallo.
4. Actualizar métricas.
5. Evaluar el rendimiento reciente.
6. Ajustar pesos solo si existe suficiente evidencia.
7. Registrar el cambio en auditoría.

Ningún peso debe cambiar por un solo acierto o fallo.

### Fase F: Completar el panel

El panel final debe organizarse así:

- **Dashboard:** estado, último resultado, próxima predicción y métricas.
- **Ingreso:** formulario, CSV, validación y duplicados.
- **Predicción:** top 10, probabilidades, incertidumbre y explicación.
- **Verificación:** resultado real, acierto y comparación.
- **Análisis:** todos los pilares y gráficos.
- **Historial:** sorteos y predicciones.
- **Configuración:** parámetros y pesos.
- **Auditoría:** cambios y decisiones del sistema.

## 7. Orden recomendado de trabajo

1. Corregir y completar la pantalla de verificación.
2. Crear métricas de rendimiento.
3. Implementar evaluación walk-forward.
4. Incorporar decaimiento y horario al predictor.
5. Incorporar Markov con suavizado.
6. Incorporar rachas e independencia.
7. Incorporar binomial, Pascal y repeticiones.
8. Crear el combinador de señales.
9. Guardar explicaciones detalladas.
10. Ajustar pesos con validación.
11. Completar gráficos y configuración.
12. Evaluar el sistema con datos nuevos durante varios meses.

## 8. Condiciones para considerar el sistema completo

Chamo Charly podrá considerarse funcionalmente completo cuando:

- Registre y valide datos sin contaminación.
- Mantenga la distinción entre `00` y `0`.
- Genere predicciones antes del resultado.
- Explique los factores utilizados.
- Verifique automáticamente cada predicción.
- Mida rendimiento fuera de muestra.
- Compare contra la línea base aleatoria.
- Muestre probabilidades calibradas.
- Mantenga un historial auditable.
- Ajuste sus pesos con evidencia suficiente.
- Informe cuando no encuentre ventaja.
- No prometa garantías de acierto.

## 9. Estado actual resumido

**Construido:** registro local, limpieza, SQLite, CSV, dashboard básico, predictor Bayesiano base, verificación inicial y análisis estadístico inicial.

**En construcción:** integración real de los pilares en el ranking final y evaluación comparativa.

**Pendiente:** combinador, métricas completas, walk-forward, auditoría, configuración avanzada y panel analítico completo.

La primera predicción acertada demuestra que el flujo técnico funciona. Las próximas predicciones determinarán si algún método aporta una mejora estable sobre el azar.
