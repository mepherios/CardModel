"""anyps5 — AnyPS5 (a PS5 executable relinker plus reimplemented system libraries) read as cards.

  scan.py      a checkout, read-only, as observations: every APS5_VABI definition, assembly export and
               raw-NID alias with file and line; every technical-debt entry; the shader instruction list;
               the counting rule behind AnyPS5's own progress badges, reproduced
  cards.py     observations -> packed cards (anyps5_library, anyps5_export, anyps5_debt, anyps5_instruction)
  classify.py  every gap, with its cause, from the cards and the knowledge cards (anyps5_domain,
               anyps5_cause), decided by the rules in stdlib/anyps5.card; proofs come from the logic engine
  cover.py     the coverage ladder: AnyPS5's number, then what remains once each kind of gap is taken out
  witness.py   AnyPS5's own pure code compiled next to the card model's derived semantics and compared
  cli.py       ``cardmodel anyps5 scan|cover|gaps|why|blocks|witness|check``

The checkout is never written: scanning reads files, witnessing compiles copies of nothing (the harness
includes the original file by path and builds in the model's state directory).
"""
