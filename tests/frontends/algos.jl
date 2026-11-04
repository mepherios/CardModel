# Julia: % and rem truncate, mod floors, / is float division, ÷ truncates
function gcd2(a::Int, b::Int)::Int
    while b != 0
        a, b = b, a % b
    end
    return abs(a)
end

function collatz(n::Int64)
    steps = 0
    while n > 1
        n = iseven2(n) ? n ÷ 2 : triple_plus_one(n)
        steps += 1
    end
    steps
end

iseven2(n::Int) = n % 2 == 0
triple_plus_one(n) = 3 * n + 1

function sumsq(n::Int)
    s = 0
    for i in 1:n
        s += i^2
    end
    s
end

function floormix(a::Int, b::Int)
    fld(a, b) + mod(a, b) + div(a, b) + rem(a, b)
end

half(x::Int) = x / 2
