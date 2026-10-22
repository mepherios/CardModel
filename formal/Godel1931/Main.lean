import Godel1931.Defs

/-!
Reads one call per line from stdin, `name arg …`, and prints each result on its own line. An argument is a
natural number in decimal, `S1.11.17.13` for the code of a sign sequence (built here, so no huge decimal is
ever parsed), or `L` and such sign sequences joined by `;` for a sequence of formulas given by its items. A
result is `true`, `false`, a number below 2⁶⁴ in decimal, or a larger number's fingerprint
`N<bits>:<x mod p₁>:<x mod p₂>` (printing a million-bit number in decimal is quadratic).
-/

open Godel1931

inductive Arg where
  | n (v : Nat)
  | l (v : List Nat)
  deriving Inhabited

def signs (s : String) : Nat := code ((s.splitOn ".").filter (· ≠ "") |>.map String.toNat!)

def parseArg (s : String) : Arg :=
  if s.startsWith "L" then
    Arg.l ((s.replace "L" "").splitOn ";" |>.filter (· ≠ "") |>.map signs)
  else if s.startsWith "S" then Arg.n (signs (s.replace "S" ""))
  else Arg.n s.toNat!

def P1 : Nat := 2305843009213693951   -- 2^61 - 1
def P2 : Nat := 2305843009213693921   -- a prime below it

def fmt (x : Nat) : String :=
  if x < 2 ^ 64 then toString x else s!"N{Nat.log2 x + 1}:{x % P1}:{x % P2}"

def num : Arg → Nat
  | .n v => v
  | .l _ => 0

def lst : Arg → List Nat
  | .l v => v
  | .n _ => []

def call (name : String) (a : Array Arg) : String :=
  let n (i : Nat) := num a[i]!
  let b (v : Bool) := if v then "true" else "false"
  match name with
  | "divides" => b (divides (n 0) (n 1))
  | "isPrime" => b (isPrime (n 0))
  | "prFactor" => fmt (prFactor (n 0) (n 1))
  | "factorial" => fmt (factorial (n 0))
  | "nthPrime" => fmt (nthPrime (n 0))
  | "item" => fmt (item (n 0) (n 1))
  | "length" => fmt (length (n 0))
  | "concat" => fmt (concat (n 0) (n 1))
  | "seq" => fmt (seq (n 0))
  | "paren" => fmt (paren (n 0))
  | "vtype" => b (vtype (n 0) (n 1))
  | "isVar" => b (isVar (n 0))
  | "not" => fmt (neg (n 0))
  | "or" => fmt (disj (n 0) (n 1))
  | "forall" => fmt (all (n 0) (n 1))
  | "succN" => fmt (succN (n 0) (n 1))
  | "number" => fmt (number (n 0))
  | "stype1" => b (stype1 (n 0))
  | "stype" => b (stype (n 0) (n 1))
  | "elFm" => b (elFm (n 0))
  | "op" => b (op (n 0) (n 1) (n 2))
  | "fmSeq" => b (fmSeq (lst a[0]!))
  | "isFm" => b (isFm (n 0))
  | "bound" => b (bound (n 0) (n 1) (n 2))
  | "freeAt" => b (freeAt (n 0) (n 1) (n 2))
  | "free" => b (free (n 0) (n 1))
  | "insert" => fmt (insert (n 0) (n 1) (n 2))
  | "freePlace" => fmt (freePlace (n 0) (n 1) (n 2))
  | "nFreePlaces" => fmt (nFreePlaces (n 0) (n 1))
  | "substK" => fmt (substK (n 0) (n 1) (n 2) (n 3))
  | "subst" => fmt (subst (n 0) (n 1) (n 2))
  | "imp" => fmt (imp (n 0) (n 1))
  | "and" => fmt (conj (n 0) (n 1))
  | "equiv" => fmt (equiv (n 0) (n 1))
  | "exists" => fmt (ex (n 0) (n 1))
  | "typeLift" => fmt (typeLift (n 0) (n 1))
  | "peanoAxiom" => b (peanoAxiom (n 0))
  | "prop1Axiom" => b (prop1Axiom (n 0))
  | "prop2Axiom" => b (prop2Axiom (n 0))
  | "prop3Axiom" => b (prop3Axiom (n 0))
  | "prop4Axiom" => b (prop4Axiom (n 0))
  | "propAxiom" => b (propAxiom (n 0))
  | "quantor1AxiomCondition" => b (quantor1AxiomCondition (n 0) (n 1) (n 2))
  | "quantor1Axiom" => b (quantor1Axiom (n 0))
  | "quantor2Axiom" => b (quantor2Axiom (n 0))
  | "reduAxiom" => b (reduAxiom (n 0))
  | "setAxiom" => b (setAxiom (n 0))
  | "isAxiom" => b (isAxiom (n 0))
  | "immConseq" => b (immConseq (n 0) (n 1) (n 2))
  | "isProofFigure" => b (isProofFigure (lst a[0]!))
  | "proofFor" => b (proofFor (lst a[0]!) (n 1))
  | other => s!"unknown {other}"

def main : IO Unit := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let mut line ← stdin.getLine
  while line != "" do
    let parts := ((line.replace "\n" "").replace "\r" "").splitOn " " |>.filter (· ≠ "")
    match parts with
    | name :: args => stdout.putStrLn (call name (args.map parseArg).toArray)
    | [] => pure ()
    line ← stdin.getLine
