import pandas as pd
import json
import os

# Cargar Excel
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "xlsx")
EXCEL_PATH = os.path.join(DATA_DIR, "cie-10es.xlsx")
df = pd.read_excel(EXCEL_PATH)

JSON_DIR = os.path.join(BASE_DIR, "json")
os.makedirs(JSON_DIR, exist_ok=True)

all_nodes = {}
for _, row in df.iterrows():
    all_nodes[row["Code"]] = {
        "Title": row["Title"],
        "Final": int(row["Final"])
    }

# Guardar JSON
output_path = os.path.join(JSON_DIR, "cie10es.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(all_nodes, f, ensure_ascii=False, indent=2)

print(f"JSON generado: {output_path}")