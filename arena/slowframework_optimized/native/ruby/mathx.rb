def checksum_pow__modpow_square_multiply(a, b, m)
  r = 0
  x = 0
  e = 0
  r = ((1) % m)
  x = (a % m)
  e = b
  while (e > (0))
    if ((e % (2)) == (1))
      r = ((r * x) % m)
    end
    x = ((x * x) % m)
    e = (e / (2))
  end
  return r
end

def checksum_pow__original(a, b, m)
  r = 0
  cm_u = 0
  cm_it1 = 0
  cm_stop2 = 0
  r = ((1) % m)
  cm_it1 = (0)
  cm_stop2 = b
  while (cm_it1 < cm_stop2)
    cm_u = cm_it1
    cm_it1 = (cm_it1 + (1))
    r = ((r * a) % m)
  end
  return r
end

def checksum_pow(a, b, m)
  if ((b >= (0)) && (m >= (1)))
    return checksum_pow__modpow_square_multiply(a, b, m)
  end
  return checksum_pow__original(a, b, m)
end

def cm_min_i(a, b)
  b < a ? b : a
end
def choose__binomial_multiplicative(n, k)
  c = 0
  i = 0
  cm_it1 = 0
  cm_stop2 = 0
  if ((k < (0)) || (k > n))
    return (0)
  end
  k = cm_min_i(k, (n - k))
  c = (1)
  cm_it1 = (0)
  cm_stop2 = k
  while (cm_it1 < cm_stop2)
    i = cm_it1
    cm_it1 = (cm_it1 + (1))
    c = ((c * (n - i)) / (i + (1)))
  end
  return c
end

def choose__original(n, k)
  a = 0
  i = 0
  cm_it1 = 0
  cm_stop2 = 0
  b = 0
  cm_it3 = 0
  cm_stop4 = 0
  c = 0
  cm_it5 = 0
  cm_stop6 = 0
  if ((k < (0)) || (k > n))
    return (0)
  end
  a = (1)
  cm_it1 = (2)
  cm_stop2 = (n + (1))
  while (cm_it1 < cm_stop2)
    i = cm_it1
    cm_it1 = (cm_it1 + (1))
    a = (a * i)
  end
  b = (1)
  cm_it3 = (2)
  cm_stop4 = (k + (1))
  while (cm_it3 < cm_stop4)
    i = cm_it3
    cm_it3 = (cm_it3 + (1))
    b = (b * i)
  end
  c = (1)
  cm_it5 = (2)
  cm_stop6 = ((n - k) + (1))
  while (cm_it5 < cm_stop6)
    i = cm_it5
    cm_it5 = (cm_it5 + (1))
    c = (c * i)
  end
  return (a / (b * c))
end

def choose(n, k)
  if (n >= (0))
    return choose__binomial_multiplicative(n, k)
  end
  return choose__original(n, k)
end

def common_period__lcm_via_gcd(a, b)
  a = ((a).abs)
  b = ((b).abs)
  if ((a == (0)) || (b == (0)))
    return (0)
  end
  return ((a / ((a).gcd(b))) * b)
end

def common_period(a, b)
  return common_period__lcm_via_gcd(a, b)
end

def digit_root__digital_root_closed_form(n)
  n = ((n).abs)
  if (n == (0))
    return (0)
  end
  return ((1) + ((n - (1)) % (9)))
end

def digit_root(n)
  return digit_root__digital_root_closed_form(n)
end

def divisor_sum__sum_of_divisors_sqrt_pairs(n)
  s = 0
  d = 0
  if (n <= (0))
    return (0)
  end
  s = (0)
  d = (1)
  while ((d * d) <= n)
    if ((n % d) == (0))
      s = (s + d)
      if ((d * d) != n)
        s = (s + (n / d))
      end
    end
    d = (d + (1))
  end
  return s
end

def divisor_sum(n)
  return divisor_sum__sum_of_divisors_sqrt_pairs(n)
end

def int_power__power_square_multiply(base, exp)
  r = 0
  x = 0
  e = 0
  r = (1)
  x = base
  e = exp
  while (e > (0))
    if ((e % (2)) == (1))
      r = (r * x)
    end
    x = (x * x)
    e = (e / (2))
  end
  return r
end

def int_power__original(base, exp)
  r = 0
  cm_u = 0
  cm_it1 = 0
  cm_stop2 = 0
  r = (1)
  cm_it1 = (0)
  cm_stop2 = exp
  while (cm_it1 < cm_stop2)
    cm_u = cm_it1
    cm_it1 = (cm_it1 + (1))
    r = (r * base)
  end
  return r
end

def int_power(base, exp)
  if (exp >= (0))
    return int_power__power_square_multiply(base, exp)
  end
  return int_power__original(base, exp)
end

def is_prime_level__is_prime_wheel_6k(n)
  d = 0
  if (n < (2))
    return false
  end
  if (n < (4))
    return true
  end
  if (((n % (2)) == (0)) || ((n % (3)) == (0)))
    return false
  end
  d = (5)
  while ((d * d) <= n)
    if (((n % d) == (0)) || ((n % (d + (2))) == (0)))
      return false
    end
    d = (d + (6))
  end
  return true
end

def is_prime_level(n)
  return is_prime_level__is_prime_wheel_6k(n)
end

def is_texture_size__is_power_of_two_bit_trick(n)
  return ((n > (0)) && ((n & (n - (1))) == (0)))
end

def is_texture_size(n)
  return is_texture_size__is_power_of_two_bit_trick(n)
end

def isqrt_slow__isqrt_newton(n)
  x = 0
  y = 0
  if (n < (2))
    return n
  end
  x = n
  y = ((x + (1)) / (2))
  while (y < x)
    x = y
    y = ((x + (n / x)) / (2))
  end
  return x
end

def isqrt_slow__original(n)
  r = 0
  r = (0)
  while (((r + (1)) * (r + (1))) <= n)
    r = (r + (1))
  end
  return r
end

def isqrt_slow(n)
  if (n >= (0))
    return isqrt_slow__isqrt_newton(n)
  end
  return isqrt_slow__original(n)
end

def reduce_ratio__gcd_builtin(a, b)
  return ((a).gcd(b))
end

def reduce_ratio(a, b)
  return reduce_ratio__gcd_builtin(a, b)
end

def set_bits__popcount_kernighan(flags)
  c = 0
  c = (0)
  while (flags != (0))
    flags = (flags & (flags - (1)))
    c = (c + (1))
  end
  return c
end

def set_bits__original(flags)
  c = 0
  c = (0)
  while (flags != (0))
    c = (c + (flags & (1)))
    flags = (flags >> (1))
  end
  return c
end

def set_bits(flags)
  if (flags >= (0))
    return set_bits__popcount_kernighan(flags)
  end
  return set_bits__original(flags)
end

def total_points__sum_1_to_n_closed_form(n)
  if (n <= (0))
    return (0)
  end
  return ((n * (n + (1))) / (2))
end

def total_points(n)
  return total_points__sum_1_to_n_closed_form(n)
end

def wave_size__fibonacci_iterative(n)
  a = 0
  b = 0
  cm_u = 0
  cm_it1 = 0
  cm_stop2 = 0
  cm_t3 = 0
  cm_t4 = 0
  a = (0)
  b = (1)
  cm_it1 = (0)
  cm_stop2 = n
  while (cm_it1 < cm_stop2)
    cm_u = cm_it1
    cm_it1 = (cm_it1 + (1))
    cm_t3 = b
    cm_t4 = (a + b)
    a = cm_t3
    b = cm_t4
  end
  return a
end

def wave_size__original(n)
  if (n < (2))
    return n
  end
  return (wave_size((n - (1))) + wave_size((n - (2))))
end

def wave_size(n)
  if (n >= (0))
    return wave_size__fibonacci_iterative(n)
  end
  return wave_size__original(n)
end
