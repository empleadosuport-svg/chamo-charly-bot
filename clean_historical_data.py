from chamo_charly.importer import clean_file


if __name__ == "__main__":
    count, warnings = clean_file(
        "entrenamiento datos reales.txt",
        "data/entrenamiento_datos_reales_limpio.csv",
    )
    print(f"Registros únicos escritos: {count}")
    for warning in warnings:
        print(f"ADVERTENCIA: {warning}")