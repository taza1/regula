"""Create a whitelist-only source archive; never include local .env, databases or reports."""
from pathlib import Path
import hashlib
import zipfile


def package(output=None):
    root = Path(__file__).resolve().parents[1]
    output = Path(output or root / '.build' / 'research-agent.zip')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = {'main.py': root/'hosted_agent/main.py',
             'requirements.txt': root/'hosted_agent/requirements.txt',
             'src/config.py': root/'src/config.py', 'src/model_client.py': root/'src/model_client.py'}
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('src/__init__.py', '')
        for name, path in files.items():
            archive.writestr(name, path.read_bytes())
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == '__main__':
    path, sha = package()
    print(f'{path}\nSHA256: {sha}')
