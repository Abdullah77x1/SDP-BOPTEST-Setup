"""Verify the distribution manifest and the original copied collector source."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(root=ROOT):
    root = Path(root)
    entries = json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
    for name, expected in entries.items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Missing/unsafe packaged file: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Checksum mismatch: '+name)
    inventory = json.loads((root/'research/SOURCE_INVENTORY.json').read_text(encoding='utf-8'))
    for original, packaged in inventory.get('copied_unchanged', {}).items():
        expected = inventory['files'][original]
        path = (root/packaged).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('Missing original-source copy: '+packaged)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Original-source mismatch: '+packaged)
    print('PASS: distribution hashes and original source-copy hash')

if __name__ == '__main__': check()
