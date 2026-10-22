/-!
# Content vectors

A model's content is its exponent vector over the prime ledger: `v i` is the exponent of
concept `i` (the `i`-th prime). Only finitely many coordinates are ever nonzero in the card
model, but the lattice laws hold for every vector, so the type is simply `Nat → Nat`, and no
content integer (the product of primes) is ever built (storage rule 1 of the research handover).

This file holds the vector operations and the finite sums every later file uses.
-/

namespace GodelCore

/-- An exponent vector: concept index ↦ exponent. -/
abbrev Vec := Nat → Nat

/-- The product of two models: exponents add. -/
def mul (u v : Vec) : Vec := fun i => u i + v i

/-- The unit model (the integer 1): every exponent zero. -/
def one : Vec := fun _ => 0

/-- gcd: the componentwise minimum. -/
def gcd (u v : Vec) : Vec := fun i => min (u i) (v i)

/-- lcm: the componentwise maximum. -/
def lcm (u v : Vec) : Vec := fun i => max (u i) (v i)

/-- Divisibility: `u ∣ v` exactly when no exponent of `u` exceeds `v`'s. -/
def Dvd (u v : Vec) : Prop := ∀ i, u i ≤ v i

/-- The basis vector of concept `i` (the `i`-th prime itself). -/
def basis (i : Nat) : Vec := fun j => if j = i then 1 else 0

theorem mul_comm (u v : Vec) : mul u v = mul v u := by
  funext i; simp only [mul]; omega

theorem mul_assoc (u v w : Vec) : mul (mul u v) w = mul u (mul v w) := by
  funext i; simp only [mul]; omega

theorem mul_one (u : Vec) : mul u one = u := by
  funext i; simp only [mul, one]; omega

/-- Finite sums `f 0 + … + f (n-1)`, by recursion so every lemma is by induction. -/
def sumTo : Nat → (Nat → Nat) → Nat
  | 0, _ => 0
  | n + 1, f => sumTo n f + f n

theorem sumTo_congr {n : Nat} {f g : Nat → Nat} (h : ∀ i, i < n → f i = g i) :
    sumTo n f = sumTo n g := by
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [sumTo]
    rw [ih (fun i hi => h i (Nat.lt_succ_of_lt hi)), h n (Nat.lt_succ_self n)]

theorem sumTo_eq_zero {n : Nat} {f : Nat → Nat} (h : ∀ i, i < n → f i = 0) : sumTo n f = 0 := by
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [sumTo]
    rw [ih (fun i hi => h i (Nat.lt_succ_of_lt hi)), h n (Nat.lt_succ_self n)]

/-- A sum with one nonzero term is that term. -/
theorem sumTo_single {n i₀ : Nat} {f : Nat → Nat} (hi : i₀ < n)
    (h : ∀ i, i < n → i ≠ i₀ → f i = 0) : sumTo n f = f i₀ := by
  induction n with
  | zero => exact absurd hi (Nat.not_lt_zero _)
  | succ n ih =>
    simp only [sumTo]
    by_cases hn : i₀ = n
    · rw [sumTo_eq_zero (fun i hi' => h i (Nat.lt_succ_of_lt hi') (by omega)), hn]
      omega
    · have hlt : i₀ < n := by omega
      rw [ih hlt (fun i hi' hne => h i (Nat.lt_succ_of_lt hi') hne),
        h n (Nat.lt_succ_self n) (fun e => hn e.symm)]
      omega

theorem sumTo_add {n : Nat} {f g : Nat → Nat} :
    sumTo n (fun i => f i + g i) = sumTo n f + sumTo n g := by
  induction n with
  | zero => rfl
  | succ n ih => simp only [sumTo, ih]; omega

end GodelCore
