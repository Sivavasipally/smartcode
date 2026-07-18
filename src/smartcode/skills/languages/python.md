### Python skill
- Target Python 3.11+; use type hints on all public functions and dataclasses/pydantic for data.
- Prefer pathlib over os.path, f-strings, context managers for resources.
- Raise specific exceptions; never bare `except:`. No mutable default arguments.
- Docstrings on public modules/classes/functions (one-line summary first).
- Imports: stdlib, third-party, local — grouped, absolute.
- Write pure functions where possible; side effects behind small, named seams.
