# Chamo Charly

Panel local para registrar y analizar resultados de Lotto Activo. Esta primera versión implementa el registro confiable de datos; todavía no genera predicciones.

## Requisitos

- Python 3.10 o superior.
- Entorno virtual recomendado.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Ejecutar el panel

```bash
streamlit run app.py --server.port 8501
```

El panel se abrirá en `http://localhost:8501` y creará la base de datos en `data/chamo_charly.db`.

## CSV

El archivo debe contener estas columnas:

```text
fecha,hora,codigo,animal
2026-09-03,10:00,30,Caimán
2026-09-03,11:00,00,Ballena
2026-09-03,12:00,0,Delfín
```

`00` y `0` son valores distintos y se validan contra el catálogo oficial.

## Pruebas

```bash
pytest -q
```

## Estado

Durante los primeros 14 días el sistema presenta estadísticas descriptivas. Las predicciones y los modelos estadísticos se incorporarán después de validar el flujo de datos y reunir suficiente histórico.
