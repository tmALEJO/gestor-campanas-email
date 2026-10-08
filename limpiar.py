"""
Limpia el/los Excel de data/ y actualiza la base (sin abrir la página).

    python limpiar.py          -> importa / actualiza desde el Excel
    python limpiar.py --mx     -> además revisa que los dominios corporativos reciban correo (DNS)
"""
import argparse

from core import db, servicio

p = argparse.ArgumentParser()
p.add_argument("--mx", action="store_true", help="verificar servidores de correo de dominios corporativos")
args = p.parse_args()

c = db.conectar()
db.respaldar("antes-limpiar")
rep = servicio.importar_excel(c)
print(f"Filas leídas:          {rep['filas']}")
print(f"Correos encontrados:   {rep['correos_encontrados']}")
print(f"Dominios corregidos:   {rep['corregidos']}")
print(f"Descartados:           {rep['invalidos']}  (ver exports/{rep['reporte_invalidos']})")
print(f"Duplicados:            {rep['duplicados']}")
print(f"Válidos únicos:        {rep['validos_unicos']}  ({rep['nuevos_en_base']} nuevos en la base)")
for h in rep["hojas"]:
    print(f"   - {h['seccion']}: {h['validos']}")
if args.mx:
    print("\nRevisando dominios (puede tardar unos minutos)...")
    print(servicio.verificar_mx(c))
