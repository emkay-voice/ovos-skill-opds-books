"""The skill is a package whose folder is the repo root: load it as one, so
its relative imports work, and put tests/ on the path for samples."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

_spec = importlib.util.spec_from_file_location("ovos_skill_opds_books", ROOT / "__init__.py",
                                               submodule_search_locations=[str(ROOT)])
skill_module = importlib.util.module_from_spec(_spec)
sys.modules["ovos_skill_opds_books"] = skill_module
_spec.loader.exec_module(skill_module)

extract = sys.modules["ovos_skill_opds_books.extract"]
opds = sys.modules["ovos_skill_opds_books.opds"]
