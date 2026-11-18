"""Extract missing official members; reject changed existing release members."""
import hashlib
from pathlib import Path
import sys
import zipfile
def install(archive, destination):
    archive, destination = Path(archive), Path(destination).resolve()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != '173a3edb67d904e114e5e88ec3e6b4a6de3b325fe68676311d84e6d500a90608': raise ValueError('Official archive checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            target = (destination/info.filename).resolve()
            if not target.is_relative_to(destination): raise ValueError('Unsafe archive member')
            if info.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
            content = source.read(info)
            if target.exists():
                if target.read_bytes() != content: raise ValueError('Modified official member: '+info.filename)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream: stream.write(content)
    print('PASS: official release members verified/extracted')
if __name__ == '__main__': install(*sys.argv[1:])
