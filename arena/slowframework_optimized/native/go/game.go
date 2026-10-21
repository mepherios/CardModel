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
func combo_bonus__sum_1_to_n_closed_form(hits int64) int64 {
	if (hits <= int64(0)) {
		return int64(0)
	}
	return cm_floordiv((hits * (hits + int64(1))), int64(2))
}

func combo_bonus(hits int64) int64 {
	return (int64(5) * combo_bonus__sum_1_to_n_closed_form(hits))
}

package cardmodel

import (
)

func damage(attack int64, defense int64, crit bool) int64 {
	var base int64 = 0
	_ = base
	base = (((attack * int64(2)) + int64(0)) - defense)
	if (base < int64(1)) {
		base = int64(1)
	}
	if crit {
		return (base * int64(2))
	}
	return base
}

package cardmodel

import (
)

func distance_sq(x1 int64, y1 int64, x2 int64, y2 int64) int64 {
	return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))
}

package cardmodel

import (
)

func in_range(x1 int64, y1 int64, x2 int64, y2 int64, radius int64) bool {
	return (distance_sq(x1, y1, x2, y2) <= (radius * radius))
}

package cardmodel

import (
)

func lerp(a float64, b float64, t float64) float64 {
	return (a + ((b - a) * t))
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
func xp_for_level__sum_of_squares_closed_form(level int64) int64 {
	if (level <= int64(0)) {
		return int64(0)
	}
	return cm_floordiv(((level * (level + int64(1))) * ((int64(2) * level) + int64(1))), int64(6))
}

func xp_for_level(level int64) int64 {
	return (int64(10) * xp_for_level__sum_of_squares_closed_form(level))
}

func level_from_xp(xp int64) int64 {
	var level int64 = 0
	_ = level
	level = int64(0)
	for (xp_for_level((level + int64(1))) <= xp) {
		level = (level + int64(1))
	}
	return level
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
func next_seed(seed int64) int64 {
	return cm_floormod(((seed * int64(1103515245)) + int64(12345)), int64(2147483648))
}

package cardmodel

import (
)

func tiles_in_circle(r int64) int64 {
	var count int64 = 0
	_ = count
	var x int64 = 0
	_ = x
	var cm_it1 int64 = 0
	_ = cm_it1
	var cm_stop2 int64 = 0
	_ = cm_stop2
	var y int64 = 0
	_ = y
	var cm_it3 int64 = 0
	_ = cm_it3
	var cm_stop4 int64 = 0
	_ = cm_stop4
	count = int64(0)
	cm_it1 = (-r)
	cm_stop2 = (r + int64(1))
	for (cm_it1 < cm_stop2) {
		x = cm_it1
		cm_it1 = (cm_it1 + int64(1))
		cm_it3 = (-r)
		cm_stop4 = (r + int64(1))
		for (cm_it3 < cm_stop4) {
			y = cm_it3
			cm_it3 = (cm_it3 + int64(1))
			if (((x * x) + (y * y)) <= (r * r)) {
				count = (count + int64(1))
			}
		}
	}
	return count
}

package cardmodel

import (
)

func cm_ipow(a int64, b int64) int64 {
	var r int64 = 1
	for b > 0 {
		if b&1 == 1 {
			r *= a
		}
		b >>= 1
		if b > 0 {
			a *= a
		}
	}
	return r
}
func trajectory_y(a int64, b int64, c int64, d int64, t int64) int64 {
	return ((((a * cm_ipow(t, int64(3))) + (b * cm_ipow(t, int64(2)))) + (c * t)) + d)
}
