# Ruby: / and % on integers floor
def gcd(a, b)
  a, b = b, a % b while b != 0
  a.abs
end

def collatz(n)
  steps = 0
  until n <= 1
    n = n.even? ? n / 2 : 3 * n + 1
    steps += 1
  end
  steps
end

def sum_to(n)
  s = 0
  (1..n).each do |i|
    next if i % 3 == 0
    s += i
  end
  s
end

def times_sum(n)
  total = 0
  n.times { |i| total += i * i }
  total
end

def floor_pair(a, b)
  return 0 if b == 0
  (a / b) * 1000 + a % b
end

def harmonic(n)
  s = 0
  1.upto(n) do |k|
    s += 1.0 / k
  end
  s
end
