"""machine — CPUs and hardware as cards, assembled into machines that run natively.

* ``isa``:     instruction cards (registry ``isa``): their semantics compile to the card IR; the interpreter's
               dispatch is generated from them.
* ``build``:   a machine card names an ISA and hardware cards; their card-language logic compiles into ONE
               card-IR module (globals, arrays, functions).
* ``native``:  that module runs in an engine: the reference interpreter (``ir``), any language card whose
               ``embed`` block says how a host loads it (``python``: in this process; ``cabi``: a shared library
               through ctypes).
* ``bench``:   per-instruction conformance: every instruction card on a flat-RAM bench, in every engine, with
               its timing and flag data checked against what its semantics do.
* ``gb`` / ``lift`` / ``shell``: the Game Boy machine, the ROM block lifter and the effect shell.

The pure core is the machine module (no I/O exists in the IR); everything that touches the world (window,
keys, audio device, save files, the clock) is the shell around it (law CM21).
"""
