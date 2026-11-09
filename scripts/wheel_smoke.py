"""Run with a Python environment where the built wheel has been installed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

with tempfile.TemporaryDirectory(prefix="notes-wheel-") as directory:
    root = Path(directory)
    db = root / "actual #notes.db"
    scripts = Path(sysconfig.get_path("scripts"))
    entry = scripts / ("notes.exe" if os.name == "nt" else "notes")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    def run(*args, success=True):
        process = subprocess.run([str(entry), "--database", str(db), *args],
                                 cwd=str(root), env=env, capture_output=True,
                                 encoding="utf-8", timeout=15)
        assert (process.returncode == 0) == success, process.stderr
        return process.stdout
    assert json.loads(run("list", "--json")) == []
    assert not db.exists()
    assert "Added note #1" in run("add", "实际 [red]note[/red]", "--body", "Unicode Straße\nbody")
    assert json.loads(run("search", "STRASSE", "--json"))[0]["body"] == "Unicode Straße\nbody"
    assert json.loads(run("show", "1", "--json"))["title"] == "实际 [red]note[/red]"
    run("show", "999", success=False)
    assert len(json.loads(run("list", "--json"))) == 1
print("Installed notes console entry point: persistent add/list/search/show passed.")
