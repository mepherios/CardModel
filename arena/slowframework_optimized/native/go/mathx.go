package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func cm_floormod(a int64, b int64) int64 {
	r := a % b
	if r != 0 && ((r < 0) != (b < 0)) {
		r += b
	}
	return r
}
func checksum_pow__modpow_square_multiply(a int64, b int64, m int64) int64 {
	var r int64 = 0
	_ = r
	var x int64 = 0
	_ = x
	var e int64 = 0
	_ = e
	r = cm_floormod(int64(1), m)
	x = cm_floormod(a, m)
	e = b
	for (e > int64(0)) {
		if (cm_floormod(e, int64(2)) == int64(1)) {
			r = cm_floormod((r * x), m)
		}
		x = cm_floormod((x * x), m)
		e = cm_floordiv(e, int64(2))
	}
	return r
}

func checksum_pow__original(a int64, b int64, m int64) int64 {
	var r int64 = 0
	_ = r
	var cm_u int64 = 0
	_ = cm_u
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	r = cm_floormod(int64(1), m)
	cm_it1 = int64(0)
	cm_stop2 = b
	for (cm_it1 < cm_stop2) {
		cm_u = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		r = cm_floormod((r * a), m)
	}
	return r
}

func checksum_pow(a int64, b int64, m int64) int64 {
	if ((b >= int64(0)) && (m >= int64(1))) {
		return checksum_pow__modpow_square_multiply(a, b, m)
	}
	return checksum_pow__original(a, b, m)
}

package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func cm_min_i(a int64, b int64) int64 {
	if b < a {
		return b
	}
	return a
}
func choose__binomial_multiplicative(n int64, k int64) int64 {
	var c int64 = 0
	_ = c
	var i int64 = 0
	_ = i
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	if ((k < int64(0)) || (k > n)) {
		return int64(0)
	}
	k = cm_min_i(k, (n - k))
	c = int64(1)
	cm_it1 = int64(0)
	cm_stop2 = k
	for (cm_it1 < cm_stop2) {
		i = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		c = cm_floordiv((c * (n - i)), (i + int64(1)))
	}
	return c
}

func choose__original(n int64, k int64) int64 {
	var a int64 = 0
	_ = a
	var i int64 = 0
	_ = i
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	var b int64 = 0
	_ = b
	var cm_it3 int64 = 0
	_ = cm_it3
	var cm_stop4 int64 = 0
	_ = cm_stop4
	var c int64 = 0
	_ = c
	var cm_it5 int64 = 0
	_ = cm_it5
	var cm_stop6 int64 = 0
	_ = cm_stop6
	if ((k < int64(0)) || (k > n)) {
		return int64(0)
	}
	a = int64(1)
	cm_it1 = int64(2)
	cm_stop2 = (n + int64(1))
	for (cm_it1 < cm_stop2) {
		i = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		a = (a * i)
	}
	b = int64(1)
	cm_it3 = int64(2)
	cm_stop4 = (k + int64(1))
	for (cm_it3 < cm_stop4) {
		i = cm_it3
		cm_it3 = (cm_it3 + int64(1))
		b = (b * i)
	}
	c = int64(1)
	cm_it5 = int64(2)
	cm_stop6 = ((n - k) + int64(1))
	for (cm_it5 < cm_stop6) {
		i = cm_it5
		cm_it5 = (cm_it5 + int64(1))
		c = (c * i)
	}
	return cm_floordiv(a, (b * c))
}

func choose(n int64, k int64) int64 {
	if (n >= int64(0)) {
		return choose__binomial_multiplicative(n, k)
	}
	return choose__original(n, k)
}

package cardmodel

import (
)

func cm_abs_i(a int64) int64 {
	if a < 0 {
		return -a
	}
	return a
}
func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func cm_gcd(a int64, b int64) int64 {
	if a < 0 {
		a = -a
	}
	if b < 0 {
		b = -b
	}
	for b != 0 {
		a, b = b, a%b
	}
	return a
}
func common_period__lcm_via_gcd(a int64, b int64) int64 {
	a = cm_abs_i(a)
	b = cm_abs_i(b)
	if ((a == int64(0)) || (b == int64(0))) {
		return int64(0)
	}
	return (cm_floordiv(a, cm_gcd(a, b)) * b)
}

func common_period(a int64, b int64) int64 {
	return common_period__lcm_via_gcd(a, b)
}

package cardmodel

import (
)

func cm_abs_i(a int64) int64 {
	if a < 0 {
		return -a
	}
	return a
}
func cm_floormod(a int64, b int64) int64 {
	r := a % b
	if r != 0 && ((r < 0) != (b < 0)) {
		r += b
	}
	return r
}
func digit_root__digital_root_closed_form(n int64) int64 {
	n = cm_abs_i(n)
	if (n == int64(0)) {
		return int64(0)
	}
	return (int64(1) + cm_floormod((n - int64(1)), int64(9)))
}

func digit_root(n int64) int64 {
	return digit_root__digital_root_closed_form(n)
}

package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func cm_floormod(a int64, b int64) int64 {
	r := a % b
	if r != 0 && ((r < 0) != (b < 0)) {
		r += b
	}
	return r
}
func divisor_sum__sum_of_divisors_sqrt_pairs(n int64) int64 {
	var s int64 = 0
	_ = s
	var d int64 = 0
	_ = d
	if (n <= int64(0)) {
		return int64(0)
	}
	s = int64(0)
	d = int64(1)
	for ((d * d) <= n) {
		if (cm_floormod(n, d) == int64(0)) {
			s = (s + d)
			if ((d * d) != n) {
				s = (s + cm_floordiv(n, d))
			}
		}
		d = (d + int64(1))
	}
	return s
}

func divisor_sum(n int64) int64 {
	return divisor_sum__sum_of_divisors_sqrt_pairs(n)
}

package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func cm_floormod(a int64, b int64) int64 {
	r := a % b
	if r != 0 && ((r < 0) != (b < 0)) {
		r += b
	}
	return r
}
func int_power__power_square_multiply(base int64, exp int64) int64 {
	var r int64 = 0
	_ = r
	var x int64 = 0
	_ = x
	var e int64 = 0
	_ = e
	r = int64(1)
	x = base
	e = exp
	for (e > int64(0)) {
		if (cm_floormod(e, int64(2)) == int64(1)) {
			r = (r * x)
		}
		x = (x * x)
		e = cm_floordiv(e, int64(2))
	}
	return r
}

func int_power__original(base int64, exp int64) int64 {
	var r int64 = 0
	_ = r
	var cm_u int64 = 0
	_ = cm_u
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	r = int64(1)
	cm_it1 = int64(0)
	cm_stop2 = exp
	for (cm_it1 < cm_stop2) {
		cm_u = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		r = (r * base)
	}
	return r
}

func int_power(base int64, exp int64) int64 {
	if (exp >= int64(0)) {
		return int_power__power_square_multiply(base, exp)
	}
	return int_power__original(base, exp)
}

package cardmodel

import (
)

func cm_floormod(a int64, b int64) int64 {
	r := a % b
	if r != 0 && ((r < 0) != (b < 0)) {
		r += b
	}
	return r
}
func is_prime_level__is_prime_wheel_6k(n int64) bool {
	var d int64 = 0
	_ = d
	if (n < int64(2)) {
		return false
	}
	if (n < int64(4)) {
		return true
	}
	if ((cm_floormod(n, int64(2)) == int64(0)) || (cm_floormod(n, int64(3)) == int64(0))) {
		return false
	}
	d = int64(5)
	for ((d * d) <= n) {
		if ((cm_floormod(n, d) == int64(0)) || (cm_floormod(n, (d + int64(2))) == int64(0))) {
			return false
		}
		d = (d + int64(6))
	}
	return true
}

func is_prime_level(n int64) bool {
	return is_prime_level__is_prime_wheel_6k(n)
}

package cardmodel

import (
)

func is_texture_size__is_power_of_two_bit_trick(n int64) bool {
	return ((n > int64(0)) && ((n & (n - int64(1))) == int64(0)))
}

func is_texture_size(n int64) bool {
	return is_texture_size__is_power_of_two_bit_trick(n)
}

package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func isqrt_slow__isqrt_newton(n int64) int64 {
	var x int64 = 0
	_ = x
	var y int64 = 0
	_ = y
	if (n < int64(2)) {
		return n
	}
	x = n
	y = cm_floordiv((x + int64(1)), int64(2))
	for (y < x) {
		x = y
		y = cm_floordiv((x + cm_floordiv(n, x)), int64(2))
	}
	return x
}

func isqrt_slow__original(n int64) int64 {
	var r int64 = 0
	_ = r
	r = int64(0)
	for (((r + int64(1)) * (r + int64(1))) <= n) {
		r = (r + int64(1))
	}
	return r
}

func isqrt_slow(n int64) int64 {
	if (n >= int64(0)) {
		return isqrt_slow__isqrt_newton(n)
	}
	return isqrt_slow__original(n)
}

package cardmodel

import (
)

func cm_gcd(a int64, b int64) int64 {
	if a < 0 {
		a = -a
	}
	if b < 0 {
		b = -b
	}
	for b != 0 {
		a, b = b, a%b
	}
	return a
}
func reduce_ratio__gcd_builtin(a int64, b int64) int64 {
	return cm_gcd(a, b)
}

func reduce_ratio(a int64, b int64) int64 {
	return reduce_ratio__gcd_builtin(a, b)
}

package cardmodel

import (
)

func set_bits__popcount_kernighan(flags int64) int64 {
	var c int64 = 0
	_ = c
	c = int64(0)
	for (flags != int64(0)) {
		flags = (flags & (flags - int64(1)))
		c = (c + int64(1))
	}
	return c
}

func set_bits__original(flags int64) int64 {
	var c int64 = 0
	_ = c
	c = int64(0)
	for (flags != int64(0)) {
		c = (c + (flags & int64(1)))
		flags = (flags >> int64(1))
	}
	return c
}

func set_bits(flags int64) int64 {
	if (flags >= int64(0)) {
		return set_bits__popcount_kernighan(flags)
	}
	return set_bits__original(flags)
}

package cardmodel

import (
)

func cm_floordiv(a int64, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}
func total_points__sum_1_to_n_closed_form(n int64) int64 {
	if (n <= int64(0)) {
		return int64(0)
	}
	return cm_floordiv((n * (n + int64(1))), int64(2))
}

func total_points(n int64) int64 {
	return total_points__sum_1_to_n_closed_form(n)
}

package cardmodel

import (
)

func wave_size__fibonacci_iterative(n int64) int64 {
	var a int64 = 0
	_ = a
	var b int64 = 0
	_ = b
	var cm_u int64 = 0
	_ = cm_u
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	var cm_t3 int64 = 0
	_ = cm_t3
	var cm_t4 int64 = 0
	_ = cm_t4
	a = int64(0)
	b = int64(1)
	cm_it1 = int64(0)
	cm_stop2 = n
	for (cm_it1 < cm_stop2) {
		cm_u = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		cm_t3 = b
		cm_t4 = (a + b)
		a = cm_t3
		b = cm_t4
	}
	return a
}

func wave_size__original(n int64) int64 {
	if (n < int64(2)) {
		return n
	}
	return (wave_size((n - int64(1))) + wave_size((n - int64(2))))
}

func wave_size(n int64) int64 {
	if (n >= int64(0)) {
		return wave_size__fibonacci_iterative(n)
	}
	return wave_size__original(n)
}
