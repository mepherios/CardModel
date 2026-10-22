import GodelCore.T1Lattice

/-!
# T3: an append-only ledger keeps every index, and inclusions preserve everything

The ledger is a list of atoms; an atom's index is its position. Appending atoms that are not yet
in the ledger (what `cardmodel/engines/godel.py:sync` does) never moves an existing atom
(`pos_append`). A content written over atoms reads as an exponent vector through the ledger
(`enc`); the reading is a homomorphism that preserves and reflects products, gcd, lcm and
divisibility, and it does not change when the ledger grows (`enc_append`), so every
factorization ever written stays valid after any expansion. The universe is the directed union
of the ledger's versions: any two versions of one append-only history have a common extension (the
longer one), and the readings agree along it (`enc_chain`). The categorical universal property
of the colimit is not formalized here.
-/

namespace GodelCore

variable {α : Type}

/-- The position of `a` in the ledger (its index); the ledger's length when absent. -/
def pos [DecidableEq α] : List α → α → Nat
  | [], _ => 0
  | x :: xs, a => if x = a then 0 else pos xs a + 1

/-- The atom at position `i`, if any. -/
def nth : List α → Nat → Option α
  | [], _ => none
  | x :: _, 0 => some x
  | _ :: xs, i + 1 => nth xs i

theorem mem_of_mem_cons_ne {x a : α} {xs : List α} (h : a ∈ x :: xs) (hx : ¬x = a) : a ∈ xs := by
  rcases List.mem_cons.mp h with h | h
  · exact absurd h.symm hx
  · exact h

/-- T3a: appending to the ledger never moves an atom: every index is permanent. -/
theorem pos_append [DecidableEq α] {l₁ l₂ : List α} {a : α} (h : a ∈ l₁) : pos (l₁ ++ l₂) a = pos l₁ a := by
  induction l₁ with
  | nil => cases h
  | cons x xs ih =>
    simp only [List.cons_append, pos]
    by_cases hx : x = a
    · simp [hx]
    · simp only [hx, ite_false]
      rw [ih (mem_of_mem_cons_ne h hx)]

theorem pos_lt_length [DecidableEq α] {l : List α} {a : α} (h : a ∈ l) : pos l a < l.length := by
  induction l with
  | nil => cases h
  | cons x xs ih =>
    simp only [pos, List.length_cons]
    by_cases hx : x = a
    · simp [hx]
    · simp only [hx, ite_false]
      have := ih (mem_of_mem_cons_ne h hx)
      omega

theorem nth_pos [DecidableEq α] {l : List α} {a : α} (h : a ∈ l) : nth l (pos l a) = some a := by
  induction l with
  | nil => cases h
  | cons x xs ih =>
    by_cases hx : x = a
    · simp [pos, nth, hx]
    · simp only [pos, hx, ite_false, nth]
      exact ih (mem_of_mem_cons_ne h hx)

theorem nth_mem {l : List α} {i : Nat} {a : α} (h : nth l i = some a) : a ∈ l := by
  induction l generalizing i with
  | nil => simp [nth] at h
  | cons x xs ih =>
    cases i with
    | zero =>
      simp only [nth, Option.some.injEq] at h
      rw [h]; exact List.mem_cons_self
    | succ i =>
      simp only [nth] at h
      exact List.mem_cons_of_mem x (ih h)

theorem nth_append_left {l₁ l₂ : List α} {i : Nat} (h : i < l₁.length) :
    nth (l₁ ++ l₂) i = nth l₁ i := by
  induction l₁ generalizing i with
  | nil => simp at h
  | cons x xs ih =>
    cases i with
    | zero => rfl
    | succ i =>
      simp only [List.cons_append, nth]
      exact ih (by simp at h; omega)

theorem nth_append_right {l₁ l₂ : List α} {i : Nat} (h : l₁.length ≤ i) :
    nth (l₁ ++ l₂) i = nth l₂ (i - l₁.length) := by
  induction l₁ generalizing i with
  | nil => simp
  | cons x xs ih =>
    cases i with
    | zero => simp at h
    | succ i =>
      simp only [List.cons_append, nth, List.length_cons]
      rw [ih (by simp at h; omega)]
      congr 1
      omega

theorem nth_length {l : List α} : nth l l.length = none := by
  induction l with
  | nil => rfl
  | cons x xs ih => simpa [nth] using ih

theorem nth_ge {l : List α} {i : Nat} (h : l.length ≤ i) : nth l i = none := by
  induction l generalizing i with
  | nil => rfl
  | cons x xs ih =>
    cases i with
    | zero => simp at h
    | succ i => simp only [nth]; exact ih (by simp at h; omega)

/-- The ledger reading of a content over atoms: coordinate `i` holds the exponent of the atom at
position `i`. -/
def enc (l : List α) (c : α → Nat) : Vec := fun i =>
  match nth l i with
  | some a => c a
  | none => 0

/-- A content uses only atoms of the ledger `l`. -/
def SupportedIn (l : List α) (c : α → Nat) : Prop := ∀ a, c a ≠ 0 → a ∈ l

/-- T3b: growing the ledger does not change the reading of anything written before. -/
theorem enc_append {l₁ l₂ : List α} {c : α → Nat} (hc : SupportedIn l₁ c)
    (hnew : ∀ a, a ∈ l₂ → a ∉ l₁) : enc (l₁ ++ l₂) c = enc l₁ c := by
  funext i
  simp only [enc]
  by_cases h : i < l₁.length
  · rw [nth_append_left h]
  · have hge : l₁.length ≤ i := by omega
    rw [nth_append_right hge, nth_ge hge]
    cases hb : nth l₂ (i - l₁.length) with
    | none => rfl
    | some b =>
      show c b = 0
      by_cases hcb : c b = 0
      · exact hcb
      · exact absurd (hc b hcb) (hnew b (nth_mem hb))

/-- T3c: the reading is a homomorphism of products, gcd and lcm. -/
theorem enc_mul (l : List α) (c d : α → Nat) :
    enc l (fun a => c a + d a) = mul (enc l c) (enc l d) := by
  funext i; simp only [enc, mul]; cases nth l i <;> rfl

theorem enc_gcd (l : List α) (c d : α → Nat) :
    enc l (fun a => min (c a) (d a)) = gcd (enc l c) (enc l d) := by
  funext i; simp only [enc, gcd]; cases nth l i <;> simp

theorem enc_lcm (l : List α) (c d : α → Nat) :
    enc l (fun a => max (c a) (d a)) = lcm (enc l c) (enc l d) := by
  funext i; simp only [enc, lcm]; cases nth l i <;> simp

/-- T3c: the reading preserves and reflects divisibility. -/
theorem enc_dvd_iff [DecidableEq α] {l : List α} {c d : α → Nat} (hc : SupportedIn l c) :
    Dvd (enc l c) (enc l d) ↔ ∀ a, c a ≤ d a := by
  constructor
  · intro h a
    by_cases ha : c a = 0
    · rw [ha]; exact Nat.zero_le _
    · have hmem := hc a ha
      have := h (pos l a)
      simp only [enc, nth_pos hmem] at this
      exact this
  · intro h i
    simp only [enc]
    cases nth l i with
    | none => exact Nat.le_refl 0
    | some a => exact h a

/-- T3c: the reading is injective on contents written in the ledger's atoms. -/
theorem enc_injective [DecidableEq α] {l : List α} {c d : α → Nat} (hc : SupportedIn l c) (hd : SupportedIn l d)
    (h : enc l c = enc l d) : c = d := by
  have e1 : Dvd (enc l c) (enc l d) := by rw [h]; exact dvd_refl _
  have e2 : Dvd (enc l d) (enc l c) := by rw [h]; exact dvd_refl _
  have h1 := (enc_dvd_iff hc).mp e1
  have h2 := (enc_dvd_iff hd).mp e2
  funext a
  exact Nat.le_antisymm (h1 a) (h2 a)

/-- T3d: along one append-only history (`l₂` extends `l₁`, `l₃` extends `l₂`), the readings of a
content written in `l₁` agree in every later version: the cocone of the directed union. -/
theorem enc_chain {l₁ t₁ t₂ : List α} {c : α → Nat} (hc : SupportedIn l₁ c)
    (h₁ : ∀ a, a ∈ t₁ → a ∉ l₁) (h₂ : ∀ a, a ∈ t₂ → a ∉ l₁ ++ t₁) :
    enc (l₁ ++ t₁ ++ t₂) c = enc l₁ c ∧ enc (l₁ ++ t₁) c = enc l₁ c := by
  have hc₂ : SupportedIn (l₁ ++ t₁) c := fun a ha => List.mem_append_left t₁ (hc a ha)
  exact ⟨(enc_append hc₂ h₂).trans (enc_append hc h₁), enc_append hc h₁⟩

end GodelCore
