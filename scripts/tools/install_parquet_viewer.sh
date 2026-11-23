#!/usr/bin/env bash
set -e

# Make "Open With > Parquet viewer" (and a double click) open .parquet files in scripts/tools/parquet_view.py.
# Writes ~/.local/share/applications/cleany-parquet-viewer.desktop and makes it the default for parquet.
# Undo: rm ~/.local/share/applications/cleany-parquet-viewer.desktop && update-desktop-database ~/.local/share/applications

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APPS="$HOME/.local/share/applications"
MIME="application/vnd.apache.parquet"
mkdir -p "$APPS"
cat > "$APPS/cleany-parquet-viewer.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Parquet viewer
Comment=Flat table view of a parquet file (Cleany)
Exec=$PROJECT_ROOT/.venv/bin/python $SCRIPT_DIR/parquet_view.py %F
Icon=x-office-spreadsheet
Terminal=false
Categories=Utility;Development;
MimeType=$MIME;application/x-parquet;
DESKTOP
# Tell the system that *.parquet files have that type (a missing type is why the file manager does not offer the viewer)
mkdir -p "$HOME/.local/share/mime/packages"
cat > "$HOME/.local/share/mime/packages/parquet.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="$MIME"><comment>Apache Parquet</comment><glob pattern="*.parquet"/></mime-type>
</mime-info>
XML
update-mime-database "$HOME/.local/share/mime" 2>/dev/null || true
update-desktop-database "$APPS" 2>/dev/null || true
xdg-mime default cleany-parquet-viewer.desktop "$MIME"
echo "Done: double click a .parquet file, or right click > Open With > Parquet viewer."
