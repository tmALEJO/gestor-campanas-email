# Gestor de correos · Nariñotex

Herramienta local para limpiar la base de compradores, elegir correos al azar con filtros, descargarlos listos para Brevo y llevar el control de cuáles ya se usaron, cuáles son inválidos y cuáles se dieron de baja.

## Cómo funciona

```
BDD_NARIÑOTEX.xlsx  ──(limpieza)──►  data/correos.db  ◄──►  app.py (Flask)  ◄──►  página en el navegador
   (solo lectura)                    (estados reales)        127.0.0.1:5050
```

- El **Excel nunca se modifica**. Es la fuente de datos.
- Los estados (disponible, usado, inválido, baja) viven en `data/correos.db` (SQLite, un solo archivo).
- La API key de ClearBounce vive en `.env` y solo la usa el servidor Python: nunca llega a la página.
- La página no se abre con doble clic al `.html`: un navegador no puede escribir archivos del disco por seguridad. Por eso hay un servidor Python pequeño que corre solo en tu PC. El doble clic va en `iniciar.bat`.

## Estructura

```
narinotex-correos/
├── app.py              servidor local (rutas de la página)
├── limpiar.py          limpieza por consola (opcional: --mx)
├── iniciar.bat         doble clic en Windows
├── iniciar.sh          Mac / Linux
├── requirements.txt
├── .env.example        plantilla de la API key de ClearBounce (cópiala como .env)
├── .env                ← TU API key (no va a GitHub)
├── core/
│   ├── config.py       rutas y ajustes
│   ├── correos.py      reglas de validación, typos, proveedores, genéricos
│   ├── archivos.py     lectura del Excel y de archivos subidos; salida CSV/Excel para Brevo
│   ├── db.py           esquema SQLite y respaldos
│   ├── servicio.py     generar, completar, marcar, lotes, exportar/importar estado
│   ├── clearbounce.py  cliente de la API de ClearBounce (créditos, subir lista, progreso, resultados)
│   └── verificacion.py borradores: vista previa → verificar → reponer → generar
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

## Flujo normal (con ClearBounce)

1. **Generar** → filtros → cantidad → **Generar vista previa**. Todavía no se marca nada.
2. **Verificar con ClearBounce**: barra de progreso con tiempo transcurrido y restante.
3. Resultado en pantalla: **Buenos / Malos / Dudosos**. Los malos ya quedan marcados como inválidos.
   Para los dudosos eliges: dejarlos fuera, incluir solo catch-all, incluir todos o marcarlos inválidos.
4. Si faltan para llegar a lo que pediste → **Reponer y verificar** (escoge nuevos y los verifica).
5. **Generar archivo y marcar como usados** → descargas el CSV/Excel solo con los buenos.
6. Subes a Brevo. Después, los rebotes y desuscritos de Brevo van a **Marcar** como "Inválidos" o "Bajas".

Sin ClearBounce: en la vista previa pulsa **Generar sin verificar** (hace lo mismo que antes).
En **2b Completar** la casilla "Verificar los nuevos con ClearBounce" hace que solo los correos agregados pasen por la verificación.

### Créditos

- Cada correo verificado gasta 1 crédito. El saldo se ve arriba a la derecha y junto a la cantidad.
- Un correo verificado hace menos de `CB_DIAS_CACHE` días (30 por defecto) no se vuelve a pagar.
- Los dudosos quedan recordados: la casilla "No escoger los que ClearBounce ya calificó como dudosos" evita volver a escogerlos.
- Diagnóstico de la conexión: abre `http://127.0.0.1:5050/api/clearbounce/diagnostico` (la API key sale oculta).

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

Antes del primer push, revisa con `git status` que no aparezca ningún `.xlsx`, `.db`, `.csv` **ni `.env`**.

## Respaldos

Antes de cada acción que cambia datos se copia la base a `data/backups/` (se guardan las últimas 20). Para volver atrás: cierra el programa y reemplaza `data/correos.db` por un respaldo.
