"""unreal — a game engine's mathematics distilled into cards (Unreal Engine's Core math, read through clang).

  engine.py    the engine install, found through its launcher's own record (or --engine / CARDMODEL_UNREAL), its
               version, and the two builds the model compiles against: the truth build (the engine's own scalar
               path, vector intrinsics off) and the shipped build (as the engine runs here, NEON, plus its Core
               library for the functions compiled out of line)
  clangast.py  the real compiler as the C++ frontend: one typed AST per translation unit (templates instantiated,
               macros expanded, overloads resolved), read as a stream and kept compact (math files only)
  lift.py      symbolic execution of a function's AST into core terms: a struct is a list of scalar slots (unions
               overlay, arrays expand), a branch merges as IF_EXPR, a call is inlined, a C library call is an
               atom; what cannot be lifted gets its cause
  distill.py   the mathematics of each lifted function: its real view, its canonical form (engines/realnorm.py),
               semantic hash, Gödel content, number and structural tokens, its use, the identities between
               functions, and the carry map from the engine's own Gödel set to the core atoms
  witness.py   the lifted terms against the engine's own compiled code on seeded inputs (a harness built from the
               engine's headers and linked to its Core library): exact bits or the ulps between them
  cards.py     unreal_math (each function as observed), unreal_use, definitions, actions and transformations
  cli.py       ``cardmodel unreal locate|scan|show|uses|gcd|witness|cover``

The engine install is never written: the frontend and the witness compile in the model's state directory, and
the two platform headers the truth build overrides are derived copies kept there.
"""
