function checksum_pow__modpow_square_multiply(a, b, m)
  local r = 0
  local x = 0
  local e = 0
  r = ((1) % m)
  x = (a % m)
  e = b
  while (e > (0)) do
    if ((e % (2)) == (1)) then
      r = ((r * x) % m)
    end
    x = ((x * x) % m)
    e = (e // (2))
    ::cm_continue_1::
  end
  return r
end

function checksum_pow__original(a, b, m)
  local r = 0
  local _ = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  r = ((1) % m)
  cm_it1 = (0)
  cm_stop2 = b
  while (cm_it1 < cm_stop2) do
    _ = cm_it1
    cm_it1 = (cm_it1 + (1))
    r = ((r * a) % m)
    ::cm_continue_2::
  end
  return r
end

function checksum_pow(a, b, m)
  if ((b >= (0)) and (m >= (1))) then
    return checksum_pow__modpow_square_multiply(a, b, m)
  end
  return checksum_pow__original(a, b, m)
end

function cm_min_i(a, b) if b < a then return b else return a end end
function choose__binomial_multiplicative(n, k)
  local c = 0
  local i = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  if ((k < (0)) or (k > n)) then
    return (0)
  end
  k = cm_min_i(k, (n - k))
  c = (1)
  cm_it1 = (0)
  cm_stop2 = k
  while (cm_it1 < cm_stop2) do
    i = cm_it1
    cm_it1 = (cm_it1 + (1))
    c = ((c * (n - i)) // (i + (1)))
    ::cm_continue_1::
  end
  return c
end

function choose__original(n, k)
  local a = 0
  local i = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  local b = 0
  local cm_it3 = 0
  local cm_stop4 = 0
  local c = 0
  local cm_it5 = 0
  local cm_stop6 = 0
  if ((k < (0)) or (k > n)) then
    return (0)
  end
  a = (1)
  cm_it1 = (2)
  cm_stop2 = (n + (1))
  while (cm_it1 < cm_stop2) do
    i = cm_it1
    cm_it1 = (cm_it1 + (1))
    a = (a * i)
    ::cm_continue_2::
  end
  b = (1)
  cm_it3 = (2)
  cm_stop4 = (k + (1))
  while (cm_it3 < cm_stop4) do
    i = cm_it3
    cm_it3 = (cm_it3 + (1))
    b = (b * i)
    ::cm_continue_3::
  end
  c = (1)
  cm_it5 = (2)
  cm_stop6 = ((n - k) + (1))
  while (cm_it5 < cm_stop6) do
    i = cm_it5
    cm_it5 = (cm_it5 + (1))
    c = (c * i)
    ::cm_continue_4::
  end
  return (a // (b * c))
end

function choose(n, k)
  if (n >= (0)) then
    return choose__binomial_multiplicative(n, k)
  end
  return choose__original(n, k)
end

function cm_gcd(a, b)
  a = math.abs(a)
  b = math.abs(b)
  while b ~= 0 do
    a, b = b, a % b
  end
  return a
end
function common_period__lcm_via_gcd(a, b)
  a = math.abs(a)
  b = math.abs(b)
  if ((a == (0)) or (b == (0))) then
    return (0)
  end
  return ((a // cm_gcd(a, b)) * b)
end

function common_period(a, b)
  return common_period__lcm_via_gcd(a, b)
end

function digit_root__digital_root_closed_form(n)
  n = math.abs(n)
  if (n == (0)) then
    return (0)
  end
  return ((1) + ((n - (1)) % (9)))
end

function digit_root(n)
  return digit_root__digital_root_closed_form(n)
end

function divisor_sum__sum_of_divisors_sqrt_pairs(n)
  local s = 0
  local d = 0
  if (n <= (0)) then
    return (0)
  end
  s = (0)
  d = (1)
  while ((d * d) <= n) do
    if ((n % d) == (0)) then
      s = (s + d)
      if ((d * d) ~= n) then
        s = (s + (n // d))
      end
    end
    d = (d + (1))
    ::cm_continue_1::
  end
  return s
end

function divisor_sum(n)
  return divisor_sum__sum_of_divisors_sqrt_pairs(n)
end

function int_power__power_square_multiply(base, exp)
  local r = 0
  local x = 0
  local e = 0
  r = (1)
  x = base
  e = exp
  while (e > (0)) do
    if ((e % (2)) == (1)) then
      r = (r * x)
    end
    x = (x * x)
    e = (e // (2))
    ::cm_continue_1::
  end
  return r
end

function int_power__original(base, exp)
  local r = 0
  local _ = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  r = (1)
  cm_it1 = (0)
  cm_stop2 = exp
  while (cm_it1 < cm_stop2) do
    _ = cm_it1
    cm_it1 = (cm_it1 + (1))
    r = (r * base)
    ::cm_continue_2::
  end
  return r
end

function int_power(base, exp)
  if (exp >= (0)) then
    return int_power__power_square_multiply(base, exp)
  end
  return int_power__original(base, exp)
end

function is_prime_level__is_prime_wheel_6k(n)
  local d = 0
  if (n < (2)) then
    return false
  end
  if (n < (4)) then
    return true
  end
  if (((n % (2)) == (0)) or ((n % (3)) == (0))) then
    return false
  end
  d = (5)
  while ((d * d) <= n) do
    if (((n % d) == (0)) or ((n % (d + (2))) == (0))) then
      return false
    end
    d = (d + (6))
    ::cm_continue_1::
  end
  return true
end

function is_prime_level(n)
  return is_prime_level__is_prime_wheel_6k(n)
end

function is_texture_size__is_power_of_two_bit_trick(n)
  return ((n > (0)) and ((n & (n - (1))) == (0)))
end

function is_texture_size(n)
  return is_texture_size__is_power_of_two_bit_trick(n)
end

function isqrt_slow__isqrt_newton(n)
  local x = 0
  local y = 0
  if (n < (2)) then
    return n
  end
  x = n
  y = ((x + (1)) // (2))
  while (y < x) do
    x = y
    y = ((x + (n // x)) // (2))
    ::cm_continue_1::
  end
  return x
end

function isqrt_slow__original(n)
  local r = 0
  r = (0)
  while (((r + (1)) * (r + (1))) <= n) do
    r = (r + (1))
    ::cm_continue_2::
  end
  return r
end

function isqrt_slow(n)
  if (n >= (0)) then
    return isqrt_slow__isqrt_newton(n)
  end
  return isqrt_slow__original(n)
end

function cm_gcd(a, b)
  a = math.abs(a)
  b = math.abs(b)
  while b ~= 0 do
    a, b = b, a % b
  end
  return a
end
function reduce_ratio__gcd_builtin(a, b)
  return cm_gcd(a, b)
end

function reduce_ratio(a, b)
  return reduce_ratio__gcd_builtin(a, b)
end

function set_bits__popcount_kernighan(flags)
  local c = 0
  c = (0)
  while (flags ~= (0)) do
    flags = (flags & (flags - (1)))
    c = (c + (1))
    ::cm_continue_1::
  end
  return c
end

function set_bits__original(flags)
  local c = 0
  c = (0)
  while (flags ~= (0)) do
    c = (c + (flags & (1)))
    flags = (flags // (1 << (1)))
    ::cm_continue_2::
  end
  return c
end

function set_bits(flags)
  if (flags >= (0)) then
    return set_bits__popcount_kernighan(flags)
  end
  return set_bits__original(flags)
end

function total_points__sum_1_to_n_closed_form(n)
  if (n <= (0)) then
    return (0)
  end
  return ((n * (n + (1))) // (2))
end

function total_points(n)
  return total_points__sum_1_to_n_closed_form(n)
end

function wave_size__fibonacci_iterative(n)
  local a = 0
  local b = 0
  local _ = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  local cm_t3 = 0
  local cm_t4 = 0
  a = (0)
  b = (1)
  cm_it1 = (0)
  cm_stop2 = n
  while (cm_it1 < cm_stop2) do
    _ = cm_it1
    cm_it1 = (cm_it1 + (1))
    cm_t3 = b
    cm_t4 = (a + b)
    a = cm_t3
    b = cm_t4
    ::cm_continue_1::
  end
  return a
end

function wave_size__original(n)
  if (n < (2)) then
    return n
  end
  return (wave_size((n - (1))) + wave_size((n - (2))))
end

function wave_size(n)
  if (n >= (0)) then
    return wave_size__fibonacci_iterative(n)
  end
  return wave_size__original(n)
end
