"""Rebuild a candidate classic Northwind SQLite file from the pinned SQL inputs."""
import gzip, sqlite3, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = __import__('json').loads((ROOT / 'manifest.json').read_text())
with tempfile.TemporaryDirectory(prefix='northwind-source-') as directory:
    path = Path(directory) / 'northwind.sqlite'
    db = sqlite3.connect(path)
    for item in manifest['source']['recipe']:
        db.executescript(gzip.decompress((ROOT / item['path']).read_bytes()).decode('utf-8'))
    db.commit()
    db.close()
    print(f'Rebuilt equivalent candidate at {path} ({path.stat().st_size} bytes). Compare with data-source/source.sqlite before updating its pin.')
