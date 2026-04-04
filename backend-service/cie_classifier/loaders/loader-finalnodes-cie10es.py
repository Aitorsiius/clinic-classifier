import json
import re
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, "json", "cie10es.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "json", "cie10es_flattened.json")


class AutoHierarchyBuilder:
    def __init__(self, data):
        self.data = data
        self.ranges = []
        self._detect_ranges()
        
    def _detect_ranges(self):
        # Detecta rangos tipo A00-B99 en claves o títulos
        pattern = re.compile(r'([A-Z]\d{2})-([A-Z]\d{2})')
        for key, info in self.data.items():
            text_to_search = f"{key} {info.get('Title', '')}"
            match = pattern.search(text_to_search)
            if match:
                start, end = match.groups()
                self.ranges.append({"id": key, "start": start, "end": end})
        self.ranges.sort(key=lambda x: x['end']) 

    def find_parent(self, code):
        # FILTRO DE SEGURIDAD: Solo procesamos códigos médicos (Letra+Digito)
        if not re.match(r'^[A-Z]\d', code):
            return None

        # 1. Jerarquía por PUNTOS (Subcategorías)
        if "." in code:
            parent_candidate = code.rsplit(".", 1)[0]
            if parent_candidate in self.data:
                return parent_candidate
        
        # 2. Jerarquía por CONTENCIÓN (Rangos)
        if "-" in code:
            match = re.search(r'([A-Z]\d{2})-([A-Z]\d{2})', code)
            if not match: return None 
            query_start, query_end = match.groups()
        else:
            query_start = query_end = code

        for r in self.ranges:
            if r["id"] == code: continue
            if r["start"] <= query_start and query_end <= r["end"]:
                return r["id"]
        return None

    def get_full_trace(self, code):
        """Devuelve una lista de diccionarios con la jerarquía completa"""
        trace = []
        curr = code
        seen = set()
        while curr and curr not in seen:
            seen.add(curr)
            parent = self.find_parent(curr)
            if parent:
                parent_data = self.data[parent]
                trace.insert(0, {
                    "code": parent,
                    "title": parent_data.get('Title', '')
                })
                curr = parent
            else:
                break
        return trace


def main():
    print(f"Cargando datos desde: {INPUT_FILE}")
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print("Error: No se encuentra el archivo de entrada.")
        return

    builder = AutoHierarchyBuilder(raw_data)
    
    flattened_records = []
    
    count = 0
    
    for code, info in raw_data.items():
        # SOLO procesamos si "Final" es 1 (o true)
        # Algunos JSON usan 1 (int), otros "1" (str), esto maneja ambos.
        is_final = str(info.get("Final", "0")) == "1"
        
        if is_final:
            # 1. Obtenemos la jerarquía (padres)
            breadcrumbs = builder.get_full_trace(code)
            
            # 2. Extraemos solo los títulos de los padres para el texto de búsqueda
            parent_titles = [b['title'] for b in breadcrumbs]
            
            # 3. Construimos el "Search Text" (Texto Semántico)
            # Concatenamos: Títulos padres + Código + Título actual
            semantic_text = " ".join(parent_titles + [code, info['Title']])
            
            # 4. Creamos el registro limpio
            record = {
                "id": code,
                "title": info['Title'],
                "search_text": semantic_text, # ESTO es lo que vectorizaremos
                "metadata": {
                    "hierarchy": breadcrumbs, # Para pintar la UI (migas de pan)
                    "type": "final"
                }
            }
            
            flattened_records.append(record)
            count += 1
            
            if count % 5000 == 0:
                print(f"   ... procesados {count} registros")
                
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(flattened_records, f, indent=2, ensure_ascii=False)
        
    print("Proceso completado con éxito")

if __name__ == "__main__":
    main()