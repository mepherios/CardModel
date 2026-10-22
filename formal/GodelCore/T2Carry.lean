import GodelCore.Basic

/-!
# T2: a carry-over preserves gcd exactly when distinct concepts have disjoint image supports

A carry-over from a Gödel set with `n` concepts is fixed by where it sends each concept: concept
`i` goes to the model `img i` (its factorization in the target set). A model `v` goes to
`∑ᵢ v i · img i`. The map always preserves products; it preserves every gcd if and only if no two
distinct concepts share a target concept. `cardmodel/engines/godel.py:preserves_gcd` computes
exactly this condition.
-/

namespace GodelCore

/-- The image of `v` under the carry-over `img` from a set of `n` concepts. -/
def carry (n : Nat) (img : Nat → Vec) (v : Vec) : Vec :=
  fun j => sumTo n (fun i => v i * img i j)

def PreservesGcd (n : Nat) (img : Nat → Vec) : Prop :=
  ∀ u v : Vec, carry n img (gcd u v) = gcd (carry n img u) (carry n img v)

def DisjointImages (n : Nat) (img : Nat → Vec) : Prop :=
  ∀ i k j, i < n → k < n → i ≠ k → img i j = 0 ∨ img k j = 0

theorem min_mul_right (a b c : Nat) : min a b * c = min (a * c) (b * c) := by
  rcases Nat.le_total a b with h | h
  · rw [Nat.min_eq_left h, Nat.min_eq_left (Nat.mul_le_mul_right c h)]
  · rw [Nat.min_eq_right h, Nat.min_eq_right (Nat.mul_le_mul_right c h)]

/-- A carry-over preserves products. -/
theorem carry_mul (n : Nat) (img : Nat → Vec) (u v : Vec) :
    carry n img (mul u v) = mul (carry n img u) (carry n img v) := by
  funext j
  simp only [carry, mul]
  rw [← sumTo_add]
  apply sumTo_congr
  intro i _
  exact Nat.add_mul _ _ _

theorem carry_one (n : Nat) (img : Nat → Vec) : carry n img one = one := by
  funext j
  exact sumTo_eq_zero (fun i _ => by simp [one])

theorem carry_basis {n i : Nat} (img : Nat → Vec) (hi : i < n) (j : Nat) :
    carry n img (basis i) j = img i j := by
  simp only [carry]
  rw [sumTo_single hi (fun k _ hk => by simp [basis, hk])]
  simp [basis]

/-- Under disjoint images each target coordinate reads at most one source concept. -/
theorem carry_point (n : Nat) (img : Nat → Vec) (hd : DisjointImages n img) (j : Nat) :
    (∀ v, carry n img v j = 0) ∨ ∃ i₀, i₀ < n ∧ ∀ v, carry n img v j = v i₀ * img i₀ j := by
  by_cases h : ∃ i₀, i₀ < n ∧ img i₀ j ≠ 0
  · obtain ⟨i₀, hi₀, hne⟩ := h
    refine Or.inr ⟨i₀, hi₀, fun v => ?_⟩
    simp only [carry]
    apply sumTo_single hi₀
    intro i hi hii
    rcases hd i i₀ j hi hi₀ hii with h0 | h0
    · simp [h0]
    · exact absurd h0 hne
  · refine Or.inl (fun v => ?_)
    simp only [carry]
    apply sumTo_eq_zero
    intro i hi
    have hz : img i j = 0 := by
      by_cases hz : img i j = 0
      · exact hz
      · exact absurd ⟨i, hi, hz⟩ h
    simp [hz]

/-- T2. -/
theorem preservesGcd_iff_disjoint (n : Nat) (img : Nat → Vec) :
    PreservesGcd n img ↔ DisjointImages n img := by
  constructor
  · intro hp i k j hi hk hik
    have h := congrFun (hp (basis i) (basis k)) j
    have hz : gcd (basis i) (basis k) = one := by
      funext x
      simp only [gcd, basis, one]
      by_cases h1 : x = i <;> by_cases h2 : x = k <;> simp [h1, h2] <;> omega
    rw [hz, carry_one] at h
    simp only [gcd, one] at h
    rw [carry_basis img hi, carry_basis img hk] at h
    omega
  · intro hd u v
    funext j
    show carry n img (gcd u v) j = min (carry n img u j) (carry n img v j)
    rcases carry_point n img hd j with h0 | ⟨i₀, _, h1⟩
    · rw [h0 (gcd u v), h0 u, h0 v]; rfl
    · rw [h1 (gcd u v), h1 u, h1 v]
      exact min_mul_right (u i₀) (v i₀) (img i₀ j)

/-- The kernel of a carry-over, read on basis concepts: two distinct concepts with the same
image cannot be told apart in the target (a translation gap). -/
theorem carry_basis_eq_of_same_image {n i k : Nat} (img : Nat → Vec) (hi : i < n) (hk : k < n)
    (h : img i = img k) : carry n img (basis i) = carry n img (basis k) := by
  funext j
  rw [carry_basis img hi, carry_basis img hk, h]

end GodelCore
