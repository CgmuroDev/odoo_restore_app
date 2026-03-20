# Odoo Restore

Aplicacion de escritorio en PyQt6 para restaurar backups de Odoo que contengan:

- `dump.sql`
- `filestore/`

La herramienta permite:

- restaurar una base PostgreSQL desde un respaldo
- reemplazar una base existente
- copiar el `filestore`
- neutralizar la base al estilo Odoo usando archivos `data/neutralize.sql`
- guardar un historial local de restauraciones

## Requisitos

### Linux

- `python3` 3.10 o superior
- `python3-pyqt6` o `PyQt6` instalado por `pip`
- `postgresql-client`
- `rsync`

Instalacion rapida en Ubuntu/Debian:

```bash
sudo apt install python3 python3-pyqt6 postgresql-client rsync
```

### Python

Dependencia del proyecto:

```bash
pip install -r requirements.txt
```

## Estructura esperada del backup

El directorio de respaldo debe contener:

```text
mi_backup/
├── dump.sql
└── filestore/
```

Si desactivas la copia de `filestore`, solo se exige `dump.sql`.

## Como ejecutar

Desde la raiz del proyecto:

```bash
python3 src/main.py
```

## Flujo de restauracion

La aplicacion realiza este proceso:

1. Valida el directorio del backup.
2. Verifica si la base existe.
3. Si corresponde, cierra conexiones activas y elimina la base.
4. Crea la base nueva.
5. Restaura `dump.sql`.
6. Copia `filestore/`.
7. Opcionalmente neutraliza la base.
8. Registra el resultado en el historial local.

## Neutralizacion estilo Odoo

La neutralizacion no usa SQL hardcodeado de la app. Sigue el enfoque de Odoo:

- consulta los modulos instalados en `ir_module_module`
- incluye estados `installed`, `to upgrade` y `to remove`
- busca `data/neutralize.sql` para cada modulo instalado
- ejecuta cada archivo encontrado sobre la base restaurada

Para que esto funcione, debes indicar rutas fuente donde existan los modulos instalados. La app soporta rutas como:

- raiz de un repo Odoo, por ejemplo `/home/usuario/Trabajo/repos/odoo-17.0`
- un directorio `addons/`
- un directorio `odoo/addons/`
- una ruta de modulos enterprise o custom

Ejemplos de rutas:

```text
/home/soltein/Trabajo/repos/odoo-17.0
/home/soltein/Trabajo/repos/enterprise
/opt/odoo/custom-addons
```

Si activas la neutralizacion y no configuras rutas fuente, la app no inicia la restauracion.

## Configuracion en la interfaz

Campos principales:

- `Base de datos`: nombre de la base destino
- `Directorio backup`: carpeta que contiene `dump.sql`
- `Host`, `Puerto`, `Usuario`, `Password`: conexion a PostgreSQL
- `Filestore root`: carpeta base donde se copiara el filestore
- `Rutas fuentes`: rutas separadas por coma para buscar `neutralize.sql`

Opciones:

- `Copiar filestore`
- `Eliminar BD si ya existe`
- `Neutralizar BD (estilo Odoo; requiere rutas de addons)`

## Empaquetado

### Linux: paquete `.deb`

Generar paquete:

```bash
bash dist/build_deb.sh
```

Instalar:

```bash
sudo dpkg -i dist/odoo-restore_1.0.0_all.deb
sudo apt install -f
```

### Windows / macOS / Linux: ejecutable con PyInstaller

```bash
pip install PyQt6 pyinstaller
python dist/build_app.py
```

Salidas esperadas:

- Windows: `dist/OdooRestore.exe`
- macOS: `dist/OdooRestore.app`
- Linux: `dist/OdooRestore`

## Archivos principales

- `src/main.py`: punto de entrada
- `src/restore_app.py`: UI y logica de restauracion
- `dist/build_deb.sh`: construccion del paquete Debian
- `dist/build_app.py`: construccion con PyInstaller
- `docs/INSTALACION.txt`: notas de instalacion rapida

## Notas

- El historial se guarda en `~/.local/share/bd_restaurater/history.json`.
- La app depende de `psql` y `rsync`; si no estan instalados, la restauracion falla.
- La neutralizacion depende de tener acceso al codigo fuente de los modulos instalados.
