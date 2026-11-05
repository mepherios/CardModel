#!/usr/bin/env bash
# The cardmodel showcase: real commands on showcase.py. See README.md for what each step proves.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
CM="$here/../../bin/cardmodel"
cd "$here"
export CARDMODEL_SELF=0
step() { echo; echo "=== $1"; echo "\$ cardmodel ${*:2}"; "$CM" "${@:2}" 2>&1; }

step "1. translate to six languages, every function witnessed against Python" \
  translate showcase.py --to rust,go,c,javascript,ruby,lua --seed 7
step "2a. two implementations, one identity: the loop sum_to" algebra form showcase.py:sum_to
step "2b. ... and the closed form triangle" algebra form showcase.py:triangle
step "2c. their GCD as functions: equal operators, cofactor 1 | 1" algebra gcd showcase.py:sum_to showcase.py:triangle
step "3a. e-graph canonical form of poly" distill "3*x*x+2*x+1"
step "3b. e-graph: Horner form == expanded poly" distill "x*(2+3*x)+1" "3*x*x+2*x+1"
step "3c. e-graph: triangle written two ways" distill "n*(n+1)/2" "(n*n+n)/2"
step "3d. rewrite: a proof chain" rewrite --prove "a*(b+c)" "a*b+a*c"
step "4a. godel similar: poly's canonical term against every definition" godel similar --expr "((((3 * x) + 2) * x) + 1)" --limit 3
step "4b. godel cofactor: the Horner cubic over poly's canonical term" godel cofactor definition/alg__cubic_eval --expr "((((3 * x) + 2) * x) + 1)"
step "4c. godel similar: clamp's canonical term" godel similar --expr "max(min(hi, x), lo)" --limit 3
step "4d. godel factor: a term that contains clamp twice" godel factor --expr "(max(min(h, y), l) - a) * (max(min(h, y), l) - a)"
step "5a. math notation: emit sum_to" math emit showcase.py --function sum_to
step "5b. math notation round trip on every function" math roundtrip showcase.py --seed 7
