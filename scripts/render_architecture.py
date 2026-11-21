"""Regenerate exact diagrams. Requires Graphviz `dot` and pypdf for PDF merge."""
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
names=["architecture_end_to_end","architecture_components","architecture_evidence"]
for name in names:
    for fmt in ("svg","png","pdf"):
        command=["dot","-T"+fmt]
        if fmt=="png":command.append("-Gdpi=110")
        subprocess.run(command+[str(ROOT/"docs"/(name+".dot")),"-o",str(ROOT/"docs"/(name+"."+fmt))],check=True)
try:
    from pypdf import PdfWriter
except ImportError:
    raise SystemExit("Individual diagrams rendered. Install pypdf to merge the architecture PDF.")
writer=PdfWriter()
for name in names:writer.append(str(ROOT/"docs"/(name+".pdf")))
writer.write(str(ROOT/"docs/Property_Risk_Architecture.pdf"))
target=ROOT/"web/architecture";target.mkdir(exist_ok=True)
for name in names:shutil.copy2(ROOT/"docs"/(name+".svg"),target/(name+".svg"))
shutil.copy2(ROOT/"docs/Property_Risk_Architecture.pdf",target/"Property_Risk_Architecture.pdf")
print("Rendered three diagrams and combined architecture PDF.")
