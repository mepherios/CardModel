import GodelCore.T1Lattice

/-!
# T5: upward-closed properties transport to multiples, downward-closed ones to divisors

Divisibility orders models. A property proven once on a factor holds for every model that
contains it when the property is upward closed ("calls the network", "contains a hash
function"); a property proven once on a model holds for every part of it when the property is
downward closed ("uses only constant-time operations", "stays inside a fragment"). Properties
that are neither ("terminates", "is fast") need the structure layer and a proof for each model.
-/

namespace GodelCore

def UpClosed (P : Vec → Prop) : Prop := ∀ n m, Dvd n m → P n → P m

def DownClosed (P : Vec → Prop) : Prop := ∀ n m, Dvd n m → P m → P n

/-- T5, upward: proven on a factor, true of every model that contains it. -/
theorem up_transport {P : Vec → Prop} (hP : UpClosed P) {n m : Vec} (h : Dvd n m) (hn : P n) : P m :=
  hP n m h hn

/-- T5, downward: proven on a model, true of every part of it. -/
theorem down_transport {P : Vec → Prop} (hP : DownClosed P) {n m : Vec} (h : Dvd n m) (hm : P m) : P n :=
  hP n m h hm

/-- Containing a given factor is upward closed (an occurrence property). -/
theorem contains_upClosed (f : Vec) : UpClosed (fun m => Dvd f m) :=
  fun _ _ h hf => dvd_trans hf h

/-- Staying inside a fragment of concepts is downward closed. -/
theorem fragment_downClosed (F : Nat → Prop) : DownClosed (fun m => ∀ i, m i ≠ 0 → F i) := by
  intro n m h hm i hi
  apply hm i
  have := h i
  omega

/-- A bound on one concept's exponent is downward closed. -/
theorem bounded_downClosed (i k : Nat) : DownClosed (fun m => m i ≤ k) :=
  fun _ _ h hm => Nat.le_trans (h i) hm

/-- The complement of an upward-closed property is downward closed. -/
theorem not_upClosed {P : Vec → Prop} (hP : UpClosed P) : DownClosed (fun m => ¬P m) :=
  fun n m h hm hn => hm (hP n m h hn)

theorem upClosed_and {P Q : Vec → Prop} (hP : UpClosed P) (hQ : UpClosed Q) : UpClosed (fun m => P m ∧ Q m) :=
  fun n m h ⟨p, q⟩ => ⟨hP n m h p, hQ n m h q⟩

theorem upClosed_or {P Q : Vec → Prop} (hP : UpClosed P) (hQ : UpClosed Q) : UpClosed (fun m => P m ∨ Q m) :=
  fun n m h hpq => hpq.elim (fun p => Or.inl (hP n m h p)) (fun q => Or.inr (hQ n m h q))

theorem downClosed_and {P Q : Vec → Prop} (hP : DownClosed P) (hQ : DownClosed Q) :
    DownClosed (fun m => P m ∧ Q m) :=
  fun n m h ⟨p, q⟩ => ⟨hP n m h p, hQ n m h q⟩

theorem downClosed_or {P Q : Vec → Prop} (hP : DownClosed P) (hQ : DownClosed Q) :
    DownClosed (fun m => P m ∨ Q m) :=
  fun n m h hpq => hpq.elim (fun p => Or.inl (hP n m h p)) (fun q => Or.inr (hQ n m h q))

/-- The common part of two models keeps any downward-closed property of either. -/
theorem gcd_keeps_down {P : Vec → Prop} (hP : DownClosed P) {m : Vec} (hm : P m) (n : Vec) : P (gcd m n) :=
  hP _ _ (gcd_dvd_left m n) hm

/-- The smallest model containing two models keeps any upward-closed property of either. -/
theorem lcm_keeps_up {P : Vec → Prop} (hP : UpClosed P) {m : Vec} (hm : P m) (n : Vec) : P (lcm m n) :=
  hP _ _ (dvd_lcm_left m n) hm

end GodelCore
