namespace CM

partial def checksum_pow__modpow_square_multiply (a : Int) (b : Int) (m : Int) : Int := Id.run do
  let mut r : Int := 0
  let mut x : Int := 0
  let mut e : Int := 0
  r := (Int.fmod (1 : Int) m)
  x := (Int.fmod a m)
  e := b
  while (decide (e > (0 : Int))) do
    if ((Int.fmod e (2 : Int)) == (1 : Int)) then
      r := (Int.fmod (r * x) m)
    x := (Int.fmod (x * x) m)
    e := (Int.fdiv e (2 : Int))
  return r


partial def checksum_pow__original (a : Int) (b : Int) (m : Int) : Int := Id.run do
  let mut r : Int := 0
  let mut cm_u : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  r := (Int.fmod (1 : Int) m)
  cm_it1 := (0 : Int)
  cm_stop2 := b
  while (decide (cm_it1 < cm_stop2)) do
    cm_u := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    r := (Int.fmod (r * a) m)
  return r


partial def checksum_pow (a : Int) (b : Int) (m : Int) : Int := Id.run do
  if ((decide (b >= (0 : Int))) && (decide (m >= (1 : Int)))) then
    return (checksum_pow__modpow_square_multiply a b m)
  return (checksum_pow__original a b m)

end CM

namespace CM

partial def choose__binomial_multiplicative (n : Int) (k : Int) : Int := Id.run do
  let mut k : Int := k
  let mut c : Int := 0
  let mut i : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  if ((decide (k < (0 : Int))) || (decide (k > n))) then
    return (0 : Int)
  k := (min k (n - k))
  c := (1 : Int)
  cm_it1 := (0 : Int)
  cm_stop2 := k
  while (decide (cm_it1 < cm_stop2)) do
    i := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    c := (Int.fdiv (c * (n - i)) (i + (1 : Int)))
  return c


partial def choose__original (n : Int) (k : Int) : Int := Id.run do
  let mut a : Int := 0
  let mut i : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  let mut b : Int := 0
  let mut cm_it3 : Int := 0
  let mut cm_stop4 : Int := 0
  let mut c : Int := 0
  let mut cm_it5 : Int := 0
  let mut cm_stop6 : Int := 0
  if ((decide (k < (0 : Int))) || (decide (k > n))) then
    return (0 : Int)
  a := (1 : Int)
  cm_it1 := (2 : Int)
  cm_stop2 := (n + (1 : Int))
  while (decide (cm_it1 < cm_stop2)) do
    i := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    a := (a * i)
  b := (1 : Int)
  cm_it3 := (2 : Int)
  cm_stop4 := (k + (1 : Int))
  while (decide (cm_it3 < cm_stop4)) do
    i := cm_it3
    cm_it3 := (cm_it3 + (1 : Int))
    b := (b * i)
  c := (1 : Int)
  cm_it5 := (2 : Int)
  cm_stop6 := ((n - k) + (1 : Int))
  while (decide (cm_it5 < cm_stop6)) do
    i := cm_it5
    cm_it5 := (cm_it5 + (1 : Int))
    c := (c * i)
  return (Int.fdiv a (b * c))


partial def choose (n : Int) (k : Int) : Int := Id.run do
  if (decide (n >= (0 : Int))) then
    return (choose__binomial_multiplicative n k)
  return (choose__original n k)

end CM

namespace CM

partial def common_period__lcm_via_gcd (a : Int) (b : Int) : Int := Id.run do
  let mut a : Int := a
  let mut b : Int := b
  a := (Int.ofNat (Int.natAbs a))
  b := (Int.ofNat (Int.natAbs b))
  if ((a == (0 : Int)) || (b == (0 : Int))) then
    return (0 : Int)
  return ((Int.fdiv a (Int.ofNat (Int.gcd a b))) * b)


partial def common_period (a : Int) (b : Int) : Int := Id.run do
  return (common_period__lcm_via_gcd a b)

end CM

namespace CM

partial def digit_root__digital_root_closed_form (n : Int) : Int := Id.run do
  let mut n : Int := n
  n := (Int.ofNat (Int.natAbs n))
  if (n == (0 : Int)) then
    return (0 : Int)
  return ((1 : Int) + (Int.fmod (n - (1 : Int)) (9 : Int)))


partial def digit_root (n : Int) : Int := Id.run do
  return (digit_root__digital_root_closed_form n)

end CM

namespace CM

partial def divisor_sum__sum_of_divisors_sqrt_pairs (n : Int) : Int := Id.run do
  let mut s : Int := 0
  let mut d : Int := 0
  if (decide (n <= (0 : Int))) then
    return (0 : Int)
  s := (0 : Int)
  d := (1 : Int)
  while (decide ((d * d) <= n)) do
    if ((Int.fmod n d) == (0 : Int)) then
      s := (s + d)
      if ((d * d) != n) then
        s := (s + (Int.fdiv n d))
    d := (d + (1 : Int))
  return s


partial def divisor_sum (n : Int) : Int := Id.run do
  return (divisor_sum__sum_of_divisors_sqrt_pairs n)

end CM

namespace CM

partial def int_power__power_square_multiply (base : Int) (exp : Int) : Int := Id.run do
  let mut r : Int := 0
  let mut x : Int := 0
  let mut e : Int := 0
  r := (1 : Int)
  x := base
  e := exp
  while (decide (e > (0 : Int))) do
    if ((Int.fmod e (2 : Int)) == (1 : Int)) then
      r := (r * x)
    x := (x * x)
    e := (Int.fdiv e (2 : Int))
  return r


partial def int_power__original (base : Int) (exp : Int) : Int := Id.run do
  let mut r : Int := 0
  let mut cm_u : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  r := (1 : Int)
  cm_it1 := (0 : Int)
  cm_stop2 := exp
  while (decide (cm_it1 < cm_stop2)) do
    cm_u := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    r := (r * base)
  return r


partial def int_power (base : Int) (exp : Int) : Int := Id.run do
  if (decide (exp >= (0 : Int))) then
    return (int_power__power_square_multiply base exp)
  return (int_power__original base exp)

end CM

namespace CM

partial def is_prime_level__is_prime_wheel_6k (n : Int) : Bool := Id.run do
  let mut d : Int := 0
  if (decide (n < (2 : Int))) then
    return false
  if (decide (n < (4 : Int))) then
    return true
  if (((Int.fmod n (2 : Int)) == (0 : Int)) || ((Int.fmod n (3 : Int)) == (0 : Int))) then
    return false
  d := (5 : Int)
  while (decide ((d * d) <= n)) do
    if (((Int.fmod n d) == (0 : Int)) || ((Int.fmod n (d + (2 : Int))) == (0 : Int))) then
      return false
    d := (d + (6 : Int))
  return true


partial def is_prime_level (n : Int) : Bool := Id.run do
  return (is_prime_level__is_prime_wheel_6k n)

end CM

namespace CM

partial def isqrt_slow__isqrt_newton (n : Int) : Int := Id.run do
  let mut x : Int := 0
  let mut y : Int := 0
  if (decide (n < (2 : Int))) then
    return n
  x := n
  y := (Int.fdiv (x + (1 : Int)) (2 : Int))
  while (decide (y < x)) do
    x := y
    y := (Int.fdiv (x + (Int.fdiv n x)) (2 : Int))
  return x


partial def isqrt_slow__original (n : Int) : Int := Id.run do
  let mut r : Int := 0
  r := (0 : Int)
  while (decide (((r + (1 : Int)) * (r + (1 : Int))) <= n)) do
    r := (r + (1 : Int))
  return r


partial def isqrt_slow (n : Int) : Int := Id.run do
  if (decide (n >= (0 : Int))) then
    return (isqrt_slow__isqrt_newton n)
  return (isqrt_slow__original n)

end CM

namespace CM

partial def reduce_ratio__gcd_builtin (a : Int) (b : Int) : Int := Id.run do
  return (Int.ofNat (Int.gcd a b))


partial def reduce_ratio (a : Int) (b : Int) : Int := Id.run do
  return (reduce_ratio__gcd_builtin a b)

end CM

namespace CM

partial def total_points__sum_1_to_n_closed_form (n : Int) : Int := Id.run do
  if (decide (n <= (0 : Int))) then
    return (0 : Int)
  return (Int.fdiv (n * (n + (1 : Int))) (2 : Int))


partial def total_points (n : Int) : Int := Id.run do
  return (total_points__sum_1_to_n_closed_form n)

end CM

namespace CM

partial def wave_size__fibonacci_iterative (n : Int) : Int := Id.run do
  let mut a : Int := 0
  let mut b : Int := 0
  let mut cm_u : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  let mut cm_t3 : Int := 0
  let mut cm_t4 : Int := 0
  a := (0 : Int)
  b := (1 : Int)
  cm_it1 := (0 : Int)
  cm_stop2 := n
  while (decide (cm_it1 < cm_stop2)) do
    cm_u := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    cm_t3 := b
    cm_t4 := (a + b)
    a := cm_t3
    b := cm_t4
  return a


partial def wave_size__original (n : Int) : Int := Id.run do
  if (decide (n < (2 : Int))) then
    return n
  return ((wave_size (n - (1 : Int))) + (wave_size (n - (2 : Int))))


partial def wave_size (n : Int) : Int := Id.run do
  if (decide (n >= (0 : Int))) then
    return (wave_size__fibonacci_iterative n)
  return (wave_size__original n)

end CM
