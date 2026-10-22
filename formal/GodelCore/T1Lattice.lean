import GodelCore.Basic

/-!
# T1: gcd and lcm are the meet and join, and divisibility is a distributive lattice

On exponent vectors divisibility is the componentwise order, gcd is the greatest common
divisor (the meet) and lcm the least common multiple (the join). Mathlib proves the same for
`ℕ` itself (`Nat.factorization_gcd`, `Nat.factorization_lcm`); here it holds for any basis.
-/

namespace GodelCore

theorem dvd_refl (u : Vec) : Dvd u u := fun _ => Nat.le_refl _

theorem dvd_trans {u v w : Vec} (h₁ : Dvd u v) (h₂ : Dvd v w) : Dvd u w :=
  fun i => Nat.le_trans (h₁ i) (h₂ i)

theorem dvd_antisymm {u v : Vec} (h₁ : Dvd u v) (h₂ : Dvd v u) : u = v :=
  funext fun i => Nat.le_antisymm (h₁ i) (h₂ i)

theorem one_dvd (u : Vec) : Dvd one u := fun _ => Nat.zero_le _

theorem gcd_dvd_left (u v : Vec) : Dvd (gcd u v) u := fun i => by simp only [gcd]; omega

theorem gcd_dvd_right (u v : Vec) : Dvd (gcd u v) v := fun i => by simp only [gcd]; omega

/-- T1, meet: every common divisor divides the gcd. -/
theorem dvd_gcd {w u v : Vec} (hu : Dvd w u) (hv : Dvd w v) : Dvd w (gcd u v) := fun i => by
  have := hu i; have := hv i; simp only [gcd]; omega

theorem dvd_lcm_left (u v : Vec) : Dvd u (lcm u v) := fun i => by simp only [lcm]; omega

theorem dvd_lcm_right (u v : Vec) : Dvd v (lcm u v) := fun i => by simp only [lcm]; omega

/-- T1, join: the lcm divides every common multiple. -/
theorem lcm_dvd {u v w : Vec} (hu : Dvd u w) (hv : Dvd v w) : Dvd (lcm u v) w := fun i => by
  have := hu i; have := hv i; simp only [lcm]; omega

/-- T1, distributivity: the divisibility lattice is distributive. -/
theorem gcd_lcm_distrib (u v w : Vec) : gcd u (lcm v w) = lcm (gcd u v) (gcd u w) := by
  funext i; simp only [gcd, lcm]; omega

theorem lcm_gcd_distrib (u v w : Vec) : lcm u (gcd v w) = gcd (lcm u v) (lcm u w) := by
  funext i; simp only [gcd, lcm]; omega

/-- Divisibility is having a cofactor: `u ∣ v` exactly when `v = u · w` for some model `w`. -/
theorem dvd_iff_exists_mul {u v : Vec} : Dvd u v ↔ ∃ w, v = mul u w := by
  constructor
  · intro h
    exact ⟨fun i => v i - u i, funext fun i => by have := h i; simp only [mul]; omega⟩
  · rintro ⟨w, rfl⟩ i
    simp only [mul]; omega

/-- gcd · lcm = the product, coordinate by coordinate. -/
theorem mul_gcd_lcm (u v : Vec) : mul (gcd u v) (lcm u v) = mul u v := by
  funext i; simp only [mul, gcd, lcm]; omega

/-- Multiplication is cancellative, as in every free commutative monoid. -/
theorem mul_left_cancel {u v w : Vec} (h : mul w u = mul w v) : u = v := by
  funext i; have := congrFun h i; simp only [mul] at this; omega

end GodelCore
