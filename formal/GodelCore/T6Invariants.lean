import GodelCore.Basic

/-!
# T6: for balanced rules, every weight vector orthogonal to the rule deltas is a rewrite invariant

Terms are trees of operation symbols over variables (arity at most two here; wider operations
nest). A term's content counts each symbol. A rule `l → r` is balanced when every variable occurs
equally often on both sides. Then a rewrite anywhere, under any substitution, moves the content by
exactly `ψ r − ψ l` (`balanced_step`), so a weight vector `w` with `w · (ψ r − ψ l) = 0` for every
rule is conserved by every rewrite sequence (`invariant`). If `w · ψ A ≠ w · ψ B`, no sequence
turns `A` into `B`, and no search is needed. Rules that copy or drop a variable (distributivity)
are not balanced and are outside this theorem.
-/

namespace GodelCore

inductive Term
  | var (x : Nat)
  | op0 (f : Nat)
  | op1 (f : Nat) (a : Term)
  | op2 (f : Nat) (a b : Term)

namespace Term

/-- A term's content: each operation symbol counted once per occurrence. -/
def content : Term → Vec
  | var _ => one
  | op0 f => basis f
  | op1 f a => mul (basis f) (content a)
  | op2 f a b => mul (basis f) (mul (content a) (content b))

/-- How often variable `x` occurs. -/
def occ (x : Nat) : Term → Nat
  | var y => if y = x then 1 else 0
  | op0 _ => 0
  | op1 _ a => occ x a
  | op2 _ a b => occ x a + occ x b

def subst (σ : Nat → Term) : Term → Term
  | var y => σ y
  | op0 f => op0 f
  | op1 f a => op1 f (subst σ a)
  | op2 f a b => op2 f (subst σ a) (subst σ b)

/-- The substituted variables' share of coordinate `i` of the content. -/
def vshare (σ : Nat → Term) (i : Nat) : Term → Nat
  | var y => content (σ y) i
  | op0 _ => 0
  | op1 _ a => vshare σ i a
  | op2 _ a b => vshare σ i a + vshare σ i b

def VarsBelow (V : Nat) : Term → Prop
  | var y => y < V
  | op0 _ => True
  | op1 _ a => VarsBelow V a
  | op2 _ a b => VarsBelow V a ∧ VarsBelow V b

theorem content_subst (σ : Nat → Term) (i : Nat) (t : Term) :
    content (subst σ t) i = content t i + vshare σ i t := by
  induction t with
  | var y => simp [subst, content, vshare, one]
  | op0 f => simp [subst, content, vshare]
  | op1 f a ih => simp only [subst, content, vshare, mul]; rw [ih]; omega
  | op2 f a b iha ihb => simp only [subst, content, vshare, mul]; rw [iha, ihb]; omega

theorem vshare_eq_sum (σ : Nat → Term) (i V : Nat) (t : Term) (h : VarsBelow V t) :
    vshare σ i t = sumTo V (fun x => occ x t * content (σ x) i) := by
  induction t with
  | var y =>
    simp only [VarsBelow] at h
    simp only [vshare, occ]
    rw [sumTo_single h (fun x _ hx => by simp [Ne.symm hx])]
    simp
  | op0 f => simp only [vshare, occ]; exact (sumTo_eq_zero (fun x _ => by simp)).symm
  | op1 f a ih => simp only [vshare, occ]; exact ih h
  | op2 f a b iha ihb =>
    simp only [VarsBelow] at h
    simp only [vshare, occ]
    rw [iha h.1, ihb h.2, ← sumTo_add]
    apply sumTo_congr
    intro x _
    exact (Nat.add_mul _ _ _).symm

/-- A balanced rule moves the substituted variables' share by nothing. -/
theorem vshare_balanced (σ : Nat → Term) (i V : Nat) {l r : Term} (hl : VarsBelow V l) (hr : VarsBelow V r)
    (hb : ∀ x, occ x l = occ x r) : vshare σ i l = vshare σ i r := by
  rw [vshare_eq_sum σ i V l hl, vshare_eq_sum σ i V r hr]
  apply sumTo_congr
  intro x _
  rw [hb x]

end Term

/-- One-hole contexts: where in a term a rewrite happens. -/
inductive Ctx
  | hole
  | op1 (f : Nat) (c : Ctx)
  | op2L (f : Nat) (c : Ctx) (b : Term)
  | op2R (f : Nat) (a : Term) (c : Ctx)

namespace Ctx

def plug : Ctx → Term → Term
  | hole, t => t
  | op1 f c, t => .op1 f (plug c t)
  | op2L f c b, t => .op2 f (plug c t) b
  | op2R f a c, t => .op2 f a (plug c t)

/-- The content of the context's own symbols. -/
def content : Ctx → Vec
  | hole => one
  | op1 f c => mul (basis f) (content c)
  | op2L f c b => mul (basis f) (mul (content c) b.content)
  | op2R f a c => mul (basis f) (mul a.content (content c))

theorem content_plug (c : Ctx) (t : Term) (i : Nat) :
    (plug c t).content i = content c i + t.content i := by
  induction c with
  | hole => simp [plug, content, one]
  | op1 f c ih => simp only [plug, content, Term.content, mul]; rw [ih]; omega
  | op2L f c b ih => simp only [plug, content, Term.content, mul]; rw [ih]; omega
  | op2R f a c ih => simp only [plug, content, Term.content, mul]; rw [ih]; omega

end Ctx

/-- A balanced rule `l → r` applied anywhere moves the content by exactly `ψ r − ψ l`. -/
theorem balanced_step {l r : Term} {V : Nat} (hl : l.VarsBelow V) (hr : r.VarsBelow V)
    (hb : ∀ x, l.occ x = r.occ x) (c : Ctx) (σ : Nat → Term) (i : Nat) :
    (c.plug (r.subst σ)).content i + l.content i = (c.plug (l.subst σ)).content i + r.content i := by
  rw [Ctx.content_plug, Ctx.content_plug, Term.content_subst, Term.content_subst,
    Term.vshare_balanced σ i V hl hr (fun x => hb x)]
  omega

/-- Integer sums, for weights. -/
def sumZ : Nat → (Nat → Int) → Int
  | 0, _ => 0
  | n + 1, f => sumZ n f + f n

theorem sumZ_add (n : Nat) (f g : Nat → Int) : sumZ n (fun i => f i + g i) = sumZ n f + sumZ n g := by
  induction n with
  | zero => simp [sumZ]
  | succ n ih => simp only [sumZ]; rw [ih]; omega

theorem sumZ_congr {n : Nat} {f g : Nat → Int} (h : ∀ i, i < n → f i = g i) : sumZ n f = sumZ n g := by
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [sumZ]
    rw [ih (fun i hi => h i (Nat.lt_succ_of_lt hi)), h n (Nat.lt_succ_self n)]

/-- The weight `w · v` over the first `n` concepts. -/
def dot (n : Nat) (w : Nat → Int) (v : Vec) : Int := sumZ n (fun i => w i * (v i : Int))

/-- The rule's delta under a weight: `w · ψ r − w · ψ l`. -/
def delta (n : Nat) (w : Nat → Int) (l r : Term) : Int := dot n w r.content - dot n w l.content

/-- T6, one step: a weight orthogonal to a balanced rule's delta is unchanged by applying it. -/
theorem dot_step {l r : Term} {V : Nat} (hl : l.VarsBelow V) (hr : r.VarsBelow V)
    (hb : ∀ x, l.occ x = r.occ x) (n : Nat) (w : Nat → Int) (hw : delta n w l r = 0) (c : Ctx)
    (σ : Nat → Term) : dot n w (c.plug (r.subst σ)).content = dot n w (c.plug (l.subst σ)).content := by
  have key : ∀ i, w i * ((c.plug (r.subst σ)).content i : Int) + w i * (l.content i : Int) =
      w i * ((c.plug (l.subst σ)).content i : Int) + w i * (r.content i : Int) := by
    intro i
    rw [← Int.mul_add, ← Int.mul_add]
    congr 1
    have := balanced_step hl hr hb c σ i
    omega
  have sum := sumZ_congr (n := n) (fun i _ => key i)
  rw [sumZ_add, sumZ_add] at sum
  simp only [delta, dot] at hw ⊢
  omega

/-- Rewriting with a list of rules: any rule, in any context, under any substitution. -/
inductive Rewrites (R : List (Term × Term)) : Term → Term → Prop
  | refl (t : Term) : Rewrites R t t
  | step {l r : Term} (c : Ctx) (σ : Nat → Term) {u : Term} :
      (l, r) ∈ R → Rewrites R (c.plug (r.subst σ)) u → Rewrites R (c.plug (l.subst σ)) u

/-- T6: if every rule is balanced (its variables below `V`) and the weight `w` is orthogonal to
every rule's delta, then `w · ψ` is the same at both ends of every rewrite sequence. -/
theorem invariant {R : List (Term × Term)} {V n : Nat} {w : Nat → Int}
    (hbal : ∀ l r, (l, r) ∈ R → l.VarsBelow V ∧ r.VarsBelow V ∧ ∀ x, l.occ x = r.occ x)
    (hw : ∀ l r, (l, r) ∈ R → delta n w l r = 0) {s t : Term} (h : Rewrites R s t) :
    dot n w s.content = dot n w t.content := by
  induction h with
  | refl => rfl
  | step c σ hmem _ ih =>
    obtain ⟨hl, hr, hb⟩ := hbal _ _ hmem
    rw [← dot_step hl hr hb n w (hw _ _ hmem) c σ]
    exact ih

end GodelCore
