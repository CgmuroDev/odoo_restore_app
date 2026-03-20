#!/usr/bin/env bash
# Genera el paquete .deb para Restaurar Backup Odoo
set -euo pipefail

APP_NAME="odoo-restore"
VERSION="$(cat "$(dirname "$0")/../VERSION")"
ARCH="all"
PKG_DIR="${APP_NAME}_${VERSION}_${ARCH}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Limpiando build anterior..."
rm -rf "$SCRIPT_DIR/$PKG_DIR" "$SCRIPT_DIR/${PKG_DIR}.deb"

echo "==> Creando estructura del paquete..."
mkdir -p "$SCRIPT_DIR/$PKG_DIR/DEBIAN"
mkdir -p "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore"
mkdir -p "$SCRIPT_DIR/$PKG_DIR/usr/bin"
mkdir -p "$SCRIPT_DIR/$PKG_DIR/usr/share/applications"
mkdir -p "$SCRIPT_DIR/$PKG_DIR/usr/share/icons/hicolor/scalable/apps"

# -- DEBIAN/control --
cat > "$SCRIPT_DIR/$PKG_DIR/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10), python3-pyqt6, postgresql-client, rsync
Maintainer: CgmuroDev <noreply@users.noreply.github.com>
Description: Restaurar Backup Odoo
 Herramienta grafica para restaurar bases de datos Odoo
 desde respaldos que contengan dump.sql y filestore.
 Soporta configuracion de conexion PostgreSQL, copia
 de filestore, e historial de restauraciones.
EOF

SRC_DIR="$(dirname "$SCRIPT_DIR")/src"

# -- Copiar archivos de la app --
cp "$SRC_DIR/main.py" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"
cp "$SRC_DIR/restore_app.py" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"
cp "$SRC_DIR/app_meta.py" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"
cp "$SRC_DIR/update_service.py" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"
cp "$SRC_DIR/icon.svg" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"
cp "$(dirname "$SCRIPT_DIR")/VERSION" "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/"

# -- Icono al sistema --
cp "$SRC_DIR/icon.svg" "$SCRIPT_DIR/$PKG_DIR/usr/share/icons/hicolor/scalable/apps/odoo-restore.svg"

# -- Launcher script --
cat > "$SCRIPT_DIR/$PKG_DIR/usr/bin/odoo-restore" <<'LAUNCHER'
#!/usr/bin/env bash
exec python3 /opt/odoo-restore/main.py "$@"
LAUNCHER
chmod 755 "$SCRIPT_DIR/$PKG_DIR/usr/bin/odoo-restore"

# -- Desktop entry --
cat > "$SCRIPT_DIR/$PKG_DIR/usr/share/applications/odoo-restore.desktop" <<'DESKTOP'
[Desktop Entry]
Name=Odoo Restore Manager
Comment=Restaurar bases de datos Odoo desde respaldos
Exec=odoo-restore
Icon=odoo-restore
Terminal=false
Type=Application
Categories=Utility;Database;System;
Keywords=odoo;backup;restore;postgresql;database;
DESKTOP

# -- Permisos --
find "$SCRIPT_DIR/$PKG_DIR/opt" -type f -name "*.py" -exec chmod 644 {} \;
chmod 644 "$SCRIPT_DIR/$PKG_DIR/opt/odoo-restore/icon.svg"

echo "==> Construyendo paquete .deb..."
dpkg-deb --build --root-owner-group "$SCRIPT_DIR/$PKG_DIR"

echo ""
echo "==> Paquete creado: ${PKG_DIR}.deb"
echo "    Instalar con: sudo dpkg -i ${PKG_DIR}.deb"
echo "    O doble click en el archivo .deb"
echo ""
echo "    Si faltan dependencias: sudo apt install -f"
