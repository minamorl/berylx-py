"""Execute README Python examples against the installed package from any cwd."""

import re
from pathlib import Path

readme = Path(__file__).resolve().parents[1] / "README.md"
blocks = re.findall(r"```python\n(.*?)```", readme.read_text(), re.S)
for index, block in enumerate(blocks, 1):
    exec(compile(block, f"README.md:example{index}", "exec"), {})
print(f"{len(blocks)} README Python examples passed")
