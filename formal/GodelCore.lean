import GodelCore.Basic
import GodelCore.T1Lattice
import GodelCore.T2Carry
import GodelCore.T3Ledger
import GodelCore.T4Free
import GodelCore.T5Transport
import GodelCore.T6Invariants

/-!
# GodelCore — the formal core of the expanding Gödel model

The theorems the research handover asks the formal core to prove (agenda R1), over plain Lean 4
with no Mathlib: content vectors are `Nat → Nat`, a basis is a list of atoms, a carry-over is a
map from concepts to vectors. Each theorem has a card in `cards/formal_theorem/`; `cardmodel verify
--only formal` builds this library, rejects any `sorry` and checks every card names a theorem
that exists.
-/
