/-!
# Gödel's 46 definitions (1931), as Lean functions on codes

The Lean form of `cardmodel/engines/godel1931.py` (Gödel method W-1). System P's signs: 0 ↦ 1, succ ↦ 3,
¬ ↦ 5, ∨ ↦ 7, ∀ ↦ 9, ( ↦ 11, ) ↦ 13; a variable of type n is pⁿ for a prime p > 13; a sequence
n₁ … n_k is 2^n₁ · 3^n₂ · … · p_k^n_k. Definitions 1 to 45 compute Gödel's functions (relations) directly,
with the same results as his bounded searches; definition 46, `provable`, is a proposition: a Σ₁ search
with no algorithm. A sequence of formulas (definitions 22, 44, 45) is given by its items, never as its
nested Gödel number. These are executable forms, compared with the Python forms on generated codes; they
are not proved equal to the paper's literal definitions here.
-/

namespace Godel1931

def ZERO : Nat := 1
def SUCC : Nat := 3
def NOT : Nat := 5
def OR : Nat := 7
def FORALL : Nat := 9
def LP : Nat := 11
def RP : Nat := 13

/-- 1: y ∣ x, that is ∃ z ≤ x. x = y·z -/
def divides (y x : Nat) : Bool := x == 0 || (y != 0 && x % y == 0)

/-- 2 -/
def isPrime (x : Nat) : Bool := Id.run do
  if x < 2 then return false
  let mut d := 2
  while d * d ≤ x do
    if x % d == 0 then return false
    d := d + 1
  return true

partial def nextPrime (p : Nat) : Nat :=
  if isPrime (p + 1) then p + 1 else nextPrime (p + 1)

/-- 5: nthPrime 0 = 0, nthPrime 1 = 2 -/
def nthPrime (n : Nat) : Nat := Id.run do
  if n == 0 then return 0
  let mut p := 2
  for _ in [1:n] do
    p := nextPrime p
  return p

/-- 4 -/
def factorial (n : Nat) : Nat := Id.run do
  let mut out := 1
  for k in [2:n+1] do
    out := out * k
  return out

/-- (e, x / pᵉ) with pᵉ the largest power of p dividing x, by repeated squaring. -/
def valuation (x p : Nat) : Nat × Nat := Id.run do
  if x % p != 0 then return (0, x)
  let mut powers : Array Nat := #[p]
  while x % (powers.back! * powers.back!) == 0 do
    powers := powers.push (powers.back! * powers.back!)
  let mut y := x
  let mut e := 0
  let mut i := powers.size
  while i > 0 do
    i := i - 1
    if y % powers[i]! == 0 then
      y := y / powers[i]!
      e := e + 2 ^ i
  while y % p == 0 do
    y := y / p
    e := e + 1
  return (e, y)

/-- The prime factors of x with their exponents, by size. -/
def factor (x : Nat) : List (Nat × Nat) := Id.run do
  let mut out : Array (Nat × Nat) := #[]
  let mut y := x
  let mut p := 2
  while y > 1 do
    if p * p > y then
      out := out.push (y, 1)
      y := 1
    else
      let (e, r) := valuation y p
      if e > 0 then out := out.push (p, e)
      y := r
      p := nextPrime p
  return out.toList

/-- 3: the n-th prime factor of x by size, as the recursion is written: past the last factor it gives 0, then
starts again from the smallest (period: the number of factors plus one) -/
def prFactor (n x : Nat) : Nat :=
  if n == 0 || x == 0 then 0 else
    let f := factor x
    let m := n % (f.length + 1)
    if m == 0 then 0 else ((f[m - 1]?.map (·.1)).getD 0)

/-- 6: the exponent of the n-th prime factor (prFactor's cycle included) -/
def item (n x : Nat) : Nat :=
  if n == 0 || x == 0 then 0 else
    let f := factor x
    let m := n % (f.length + 1)
    if m == 0 then 0 else ((f[m - 1]?.map (·.2)).getD 0)

/-- 7 -/
def length (x : Nat) : Nat := if x < 2 then 0 else (factor x).length

def items (x : Nat) : List Nat := if x < 2 then [] else (factor x).map (·.2)

/-- 2^s₁ · 3^s₂ · … -/
def code (s : List Nat) : Nat := Id.run do
  let mut n := 1
  let mut p := 2
  for c in s do
    n := n * p ^ c
    p := nextPrime p
  return n

def isSequence (x : Nat) : Bool := Id.run do
  if x < 2 then return false
  let mut p := 2
  for (q, _) in factor x do
    if q != p then return false
    p := nextPrime p
  return true

/-- 8: x ∘ y -/
def concat (x y : Nat) : Nat := code (items x ++ items y)
/-- 9 -/
def seq (x : Nat) : Nat := 2 ^ x
/-- 10 -/
def paren (x : Nat) : Nat := code ([LP] ++ items x ++ [RP])

def isVar (x : Nat) : Bool :=
  x ≥ 17 && match factor x with
    | [(p, _)] => p > 13
    | _ => false

def varType (x : Nat) : Nat :=
  if isVar x then ((factor x).head?.map (·.2)).getD 0 else 0

/-- 11 -/
def vtype (n x : Nat) : Bool := n != 0 && isVar x && varType x == n

/-- 13, 14, 15 -/
def neg (x : Nat) : Nat := code ([NOT, LP] ++ items x ++ [RP])
def disj (x y : Nat) : Nat := code ([LP] ++ items x ++ [RP, OR, LP] ++ items y ++ [RP])
def all (x y : Nat) : Nat := code ([FORALL, x, LP] ++ items y ++ [RP])

/-- 16, 17 -/
def succN (n x : Nat) : Nat := code (List.replicate n SUCC ++ items x)
def number (n : Nat) : Nat := succN n (seq ZERO)

def stype1Signs (s : List Nat) : Bool :=
  match s.reverse with
  | [] => false
  | last :: rest => rest.all (· == SUCC) && (last == ZERO || (isVar last && varType last == 1))

def stypeSigns (n : Nat) (s : List Nat) : Bool :=
  if n == 1 then stype1Signs s
  else n > 1 && match s with
    | [v] => isVar v && varType v == n
    | _ => false

/-- 18, 19 -/
def stype1 (x : Nat) : Bool := isSequence x && stype1Signs (items x)
def stype (n x : Nat) : Bool := isSequence x && stypeSigns n (items x)

def elFmSigns (s : List Nat) : Bool :=
  match s with
  | f :: lp :: rest =>
    lp == LP && isVar f && rest.getLast? == some RP && varType f ≥ 2 &&
      stypeSigns (varType f - 1) rest.dropLast
  | _ => false

/-- 20 -/
def elFm (x : Nat) : Bool := isSequence x && elFmSigns (items x)

/-- 21 -/
def op (x y z : Nat) : Bool :=
  isSequence x && (x == neg y || x == disj y z ||
    match items x with
    | f :: v :: _ => f == FORALL && isVar v && x == all v y
    | _ => false)

/-- The end (exclusive) of the parenthesized group opening at index i. -/
def group (s : Array Nat) (i : Nat) : Option Nat := Id.run do
  if i ≥ s.size || s[i]! != LP then return none
  let mut depth : Int := 0
  for j in [i:s.size] do
    if s[j]! == LP then depth := depth + 1
    if s[j]! == RP then depth := depth - 1
    if depth == 0 then return some (j + 1)
  return none

inductive Tree where
  | el (signs : List Nat)
  | neg (a : Tree)
  | disj (a b : Tree)
  | all (v : Nat) (a : Tree)
  deriving BEq, Repr, Inhabited

partial def parse (s : Array Nat) : Option Tree :=
  if s.size == 0 then none
  else if s[0]! == NOT then
    match group s 1 with
    | some e => if e == s.size then (parse (s.extract 2 (s.size - 1))).map Tree.neg else none
    | none => none
  else if s[0]! == FORALL then
    if s.size < 2 || !isVar s[1]! then none
    else match group s 2 with
      | some e => if e == s.size then (parse (s.extract 3 (s.size - 1))).map (Tree.all s[1]!) else none
      | none => none
  else if s[0]! == LP then
    match group s 0 with
    | some mid =>
      if mid < s.size && s[mid]! == OR && group s (mid + 1) == some s.size then
        match parse (s.extract 1 (mid - 1)), parse (s.extract (mid + 2) (s.size - 1)) with
        | some a, some b => some (Tree.disj a b)
        | _, _ => none
      else none
    | none => none
  else if elFmSigns s.toList then some (Tree.el s.toList) else none

partial def signsOf : Tree → List Nat
  | .el s => s
  | .neg a => [NOT, LP] ++ signsOf a ++ [RP]
  | .disj a b => [LP] ++ signsOf a ++ [RP, OR, LP] ++ signsOf b ++ [RP]
  | .all v a => [FORALL, v, LP] ++ signsOf a ++ [RP]

def tree (x : Nat) : Option Tree := if isSequence x then parse (items x).toArray else none

/-- 22: a formula-building sequence, given by its items -/
def fmSeq (xs : List Nat) : Bool := Id.run do
  if xs.isEmpty then return false
  let a := xs.toArray
  for n in [0:a.size] do
    if elFm a[n]! then continue
    let mut ok := false
    for p in [0:n] do
      for q in [0:n] do
        if op a[n]! a[p]! a[q]! then ok := true
    if !ok then return false
  return true

/-- 23 -/
def isFm (x : Nat) : Bool := (tree x).isSome

/-- 1-based positions of s inside a subformula ∀v(b), b a formula. -/
def boundPositions (s : Array Nat) (v : Nat) : List Nat := Id.run do
  let mut out : Array Nat := #[]
  for a in [0:s.size] do
    if s[a]! == FORALL && a + 1 < s.size && s[a + 1]! == v then
      match group s (a + 2) with
      | some e =>
        if (parse (s.extract (a + 3) (e - 1))).isSome then
          for k in [a + 1:e + 1] do
            out := out.push k
      | none => pure ()
  return out.toList

/-- 24, 25, 26 -/
def bound (v n x : Nat) : Bool := isVar v && isFm x && (boundPositions (items x).toArray v).contains n

def freePlaces (v x : Nat) : List Nat :=
  if !(isVar v && isFm x) then [] else
    let s := (items x).toArray
    let b := boundPositions s v
    (List.range s.size).filterMap fun i => if s[i]! == v && !b.contains (i + 1) then some (i + 1) else none

def freeAt (v n x : Nat) : Bool := (freePlaces v x).contains n
def free (v x : Nat) : Bool := !(freePlaces v x).isEmpty

/-- 27: x with its n-th item replaced by the sequence y -/
def insert (x n y : Nat) : Nat :=
  let s := items x
  if n < 1 || n > s.length then 0 else code (s.take (n - 1) ++ items y ++ s.drop n)

/-- 28, 29: the (k+1)-th free place counted from the end, and how many there are -/
def freePlace (k v x : Nat) : Nat :=
  let p := freePlaces v x
  if k < p.length then p[p.length - 1 - k]! else 0
def nFreePlaces (v x : Nat) : Nat := (freePlaces v x).length

/-- 30, 31 -/
def substK (k x v y : Nat) : Nat := Id.run do
  let mut out := x
  for j in [0:k] do
    out := insert out (freePlace j v x) y
  return out
def subst (x v y : Nat) : Nat := substK (nFreePlaces v x) x v y

/-- 32 -/
def imp (x y : Nat) : Nat := disj (neg x) y
def conj (x y : Nat) : Nat := neg (disj (neg x) (neg y))
def equiv (x y : Nat) : Nat := conj (imp x y) (imp y x)
def ex (v y : Nat) : Nat := neg (all v (neg y))

/-- 33: every variable's type raised by n -/
def typeLift (n x : Nat) : Nat :=
  code ((items x).map fun s => if s ≤ 13 then s else s * prFactor 1 s ^ n)

def var (i typ : Nat) : Nat := nthPrime (7 + i) ^ typ
def el (f : Nat) (arg : List Nat) : Nat := code ([f, LP] ++ arg ++ [RP])
def eq (a b : List Nat) (typ : Nat) : Nat :=
  let z := var 0 (typ + 1)
  all z (imp (el z a) (el z b))

def X1 : Nat := var 0 1
def Y1 : Nat := var 1 1
def X2 : Nat := var 0 2
def Y2 : Nat := var 1 2

/-- The Peano axioms I.1–3 and the set axiom V.1, with = expanded as in P -/
def PA : List Nat :=
  [neg (eq [SUCC, X1] [ZERO] 1),
   imp (eq [SUCC, X1] [SUCC, Y1] 1) (eq [X1] [Y1] 1),
   imp (conj (el X2 [ZERO]) (all X1 (imp (el X2 [X1]) (el X2 [SUCC, X1])))) (all X1 (el X2 [X1]))]
def SA : Nat := imp (all X1 (equiv (el X2 [X1]) (el Y2 [X1]))) (eq [X2] [Y2] 2)

/-- 34 -/
def peanoAxiom (x : Nat) : Bool := PA.contains x

def impParts (x : Nat) : Option (Nat × Nat) :=
  match tree x with
  | some (.disj (.neg a) b) => some (code (signsOf a), code (signsOf b))
  | _ => none

def orParts (x : Nat) : Option (Nat × Nat) :=
  match tree x with
  | some (.disj a b) => some (code (signsOf a), code (signsOf b))
  | _ => none

/-- 35 -/
def prop1Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match orParts a with
    | some (p, q) => p == q && q == b && isFm b
    | none => false
  | none => false

def prop2Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match orParts b with
    | some (p, q) => p == a && isFm p && isFm q
    | none => false
  | none => false

def prop3Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match orParts a, orParts b with
    | some (p, q), some (q', p') => p == p' && q == q' && isFm p && isFm q
    | _, _ => false
  | none => false

def prop4Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match impParts a, impParts b with
    | some (p, q), some (rp, rq) => match orParts rp, orParts rq with
      | some (r, p'), some (r', q') => r == r' && p' == p && q' == q && isFm p && isFm q && isFm r
      | _, _ => false
    | _, _ => false
  | none => false

/-- 36 -/
def propAxiom (x : Nat) : Bool := prop1Axiom x || prop2Axiom x || prop3Axiom x || prop4Axiom x

/-- 37: substituting z for v in y captures none of z's variables -/
def quantor1AxiomCondition (z y v : Nat) : Bool :=
  let ys := (items y).toArray
  (freePlaces v y).all fun n => (items z).all fun w => !(isVar w && (boundPositions ys w).contains n)

/-- 38: ∀v.a ⇒ subst(a, v, c) -/
def quantor1Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match tree a with
    | some (.all v t) =>
      let y := code (signsOf t)
      let places := freePlaces v y
      if places.isEmpty then b == y else
        let target := items b
        let ylen := (items y).length
        let k : Int := (target.length : Int) - ((ylen : Int) - (places.length : Int))
        if k ≤ 0 || k % places.length != 0 then false else
          let width := k.toNat / places.length
          let first := places.head!
          let c := code ((target.drop (first - 1)).take width)
          stype (varType v) c && quantor1AxiomCondition c y v && subst y v c == b
    | _ => false
  | none => false

/-- 39: ∀v(p ∨ q) ⇒ p ∨ ∀v.q, v not free in p -/
def quantor2Axiom (x : Nat) : Bool :=
  match impParts x with
  | some (a, b) => match tree a with
    | some (.all v (.disj p q)) =>
      let pc := code (signsOf p)
      !free v pc && b == disj pc (all v (code (signsOf q)))
    | _ => false
  | none => false

/-- 40: ∃u ∀v (u(v) ⇔ y), u one type above v and not free in y -/
def reduAxiom (x : Nat) : Bool :=
  match tree x with
  | some (.neg (.all u (.neg (.all v body)))) =>
    match body with
    | .neg (.disj (.neg ab) _) =>
      match impParts (code (signsOf ab)) with
      | some (l, y) =>
        l == el u [v] && varType u == varType v + 1 && !free u y &&
          x == ex u (all v (equiv (el u [v]) y))
      | none => false
    | _ => false
  | _ => false

/-- 41: x = typeLift(n, sa) for some n; the lifts grow strictly, so stop past x -/
def setAxiom (x : Nat) : Bool := Id.run do
  if x < SA then return false
  for n in [0:64] do
    let l := typeLift n SA
    if l == x then return true
    if l > x then return false
  return false

/-- 42, 43 -/
def isAxiom (x : Nat) : Bool :=
  peanoAxiom x || propAxiom x || quantor1Axiom x || quantor2Axiom x || reduAxiom x || setAxiom x

def immConseq (x y z : Nat) : Bool :=
  y == imp z x || match items x with
    | f :: v :: _ => f == FORALL && isVar v && x == all v y
    | _ => false

/-- 44, 45 -/
def isProofFigure (xs : List Nat) : Bool := Id.run do
  if xs.isEmpty then return false
  let a := xs.toArray
  for n in [0:a.size] do
    if isAxiom a[n]! then continue
    let mut ok := false
    for p in [0:n] do
      for q in [0:n] do
        if immConseq a[n]! a[p]! a[q]! then ok := true
    if !ok then return false
  return true

def proofFor (xs : List Nat) (y : Nat) : Bool := isProofFigure xs && xs.getLast? == some y

/-- 46: provability is a Σ₁ proposition, not a function: some sequence is a proof of x -/
def provable (x : Nat) : Prop := ∃ y : List Nat, proofFor y x = true

end Godel1931
