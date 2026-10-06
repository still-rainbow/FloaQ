"""Check the files eligible for a fresh public commit; never print secret values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'API token': re.compile(r'\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b'),
    'credential in URL': re.compile(r'https?://[^\s/:]+:[^\s/@]+@'),
    'institution endpoint': re.compile(r'\bs{2}afy\.(?:com|io)\b|\b70\.12\.\d+\.\d+', re.I),
}
EXCLUDED = {'.pt', '.pth', '.onnx', '.engine', '.npz', '.npy', '.whl', '.db', '.sqlite', '.mp4', '.avi', '.stl'}

def main():
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT, capture_output=True)
    if result.returncode:
        print('Run this check from an initialized Git checkout.', file=sys.stderr)
        return 2
    failures = []
    files = sorted(set(filter(None, result.stdout.decode('utf-8').split('\0'))))
    for name in files:
        path = ROOT / name
        if not path.is_file():
            continue
        if path.name.startswith('.env') and path.name not in {'.env.example', '.env.fixture.example'}:
            failures.append((name, 'local environment file'))
        if path.suffix in EXCLUDED or path.stat().st_size >= 50 * 1024 * 1024:
            failures.append((name, 'model, data, calibration or oversized file'))
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            if name != 'backend/gradle/wrapper/gradle-wrapper.jar':
                failures.append((name, 'unreviewed binary'))
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for label, rule in RULES.items():
                if rule.search(line):
                    failures.append((f'{name}:{number}', label))
    for path, kind in failures:
        print(f'{path}: {kind}')
    print(f'{len(files)} source files checked; {len(failures)} findings.')
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
