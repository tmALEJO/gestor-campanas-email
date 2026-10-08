# Gestor de correos · Nariñotex

Herramienta local para limpiar la base de compradores, elegir correos al azar con filtros, descargarlos listos para Brevo y llevar el control de cuáles ya se usaron, cuáles son inválidos y cuáles se dieron de baja.

## Cómo funciona

```
BDD_NARIÑOTEX.xlsx  ──(limpieza)──►  data/correos.db  ◄──►  app.py (Flask)  ◄──►  página en el navegador
   (solo lectura)                    (estados reales)        127.0.0.1:5050
```

- El **Excel nunca se modifica**. Es la fuente de datos.
- Los estados (disponible, usado, inválido, baja) viven en `data/correos.db` (SQLite, un solo archivo).
- La página no se abre con doble clic al `.html`: un navegador no puede escribir archivos del disco por seguridad. Por eso hay un servidor Python pequeño que corre solo en tu PC. El doble clic va en `iniciar.bat`.

## Estructura

```
narinotex-correos/
├── app.py              servidor local (rutas de la página)
├── limpiar.py          limpieza por consola (opcional: --mx)
├── iniciar.bat         doble clic en Windows
├── iniciar.sh          Mac / Linux
├── requirements.txt
├── core/
│   ├── config.py       rutas y ajustes
│   ├── correos.py      reglas de validación, typos, proveedores, genéricos
│   ├── archivos.py     lectura del Excel y de archivos subidos; salida CSV/Excel para Brevo
│   ├── db.py           esquema SQLite y respaldos
│   └── servicio.py     generar, completar, marcar, lotes, exportar/importar estado
├── static/             index.html, app.js, styles.css
├── data/               ← aquí va BDD_NARIÑOTEX.xlsx (y se crea correos.db y backups/)
└── exports/            copia de cada archivo generado + reporte de descartados
```

## Instalación (una sola vez)

1. Instala Python 3.10 o superior desde python.org (marca **"Add Python to PATH"**).
2. Copia `BDD_NARIÑOTEX.xlsx` dentro de `data/`.
3. Doble clic en `iniciar.bat`. La primera vez crea `.venv` e instala Flask y openpyxl, limpia el Excel y abre el navegador en `http://127.0.0.1:5050`.
4. Deja la ventana negra abierta mientras usas la página. Ciérrala para apagar.

Manual (si prefieres la terminal de VS Code):

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Primer arranque: registrar lo que ya se envió

En la pestaña **Marcar**, elige "Ya utilizados" y sube:
- los CSV de `Correos_Envio_Gmail_Yahoo/` (los 99),
- el archivo de tu compañero (los 246),
- `historial_selecciones` / `correosUtilizados` si los tienes.

Si alguno de esos correos no está en el Excel, se registra igual (sección "Externo") para que nunca se vuelva a escoger.

## Flujo normal

1. **Generar** → filtros (país, proveedor, secciones con % o cantidad) → cantidad → descargar CSV.
2. Subes ese CSV al verificador.
3. **Marcar** → "Inválidos" → subes el archivo de malos → previsualizar → confirmar.
4. **Generar → 2b Completar** → subes el archivo de buenos + cuántos agregar → descargas el archivo completo.
5. Los nuevos que agregó también deben pasar por el verificador (repite 2-4 hasta que todo esté limpio).
6. Subes a Brevo. Después, los rebotes y desuscritos de Brevo van a **Marcar** como "Inválidos" o "Bajas".

## Estados y prioridad

`disponible < usado < inválido < baja`. Un estado más fuerte nunca se rebaja solo (si alguien se dio de baja, ningún archivo lo vuelve "usado"). Para corregir a mano, usa **Buscar**.

## Trabajar entre dos personas

Cada PC tiene su propia `correos.db`. Para no duplicar envíos:
- Lo más simple: **una sola persona genera los lotes**.
- Si ambos generan: **Base y sincronizar → Exportar "Todo"**, se lo pasas a tu compañero y él lo sube en **Importar estado** (y al revés) antes de generar.

## GitHub

Repositorio **privado**. El `.gitignore` ya excluye el Excel, la base, los respaldos y `exports/`: contienen nombres, cédulas, celulares y correos de personas reales. El Excel se comparte por Drive/OneDrive, no por Git.

```powershell
git init
git add .
git commit -m "Gestor de correos Nariñotex"
git branch -M main
git remote add origin https://github.com/tmALEJO/narinotex-correos.git
git push -u origin main
```

Antes del primer push, revisa con `git status` que no aparezca ningún `.xlsx`, `.db` ni `.csv`.

## Respaldos

Antes de cada acción que cambia datos se copia la base a `data/backups/` (se guardan las últimas 20). Para volver atrás: cierra el programa y reemplaza `data/correos.db` por un respaldo.
