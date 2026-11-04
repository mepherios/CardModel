package algos

import "math"

func gcd(a, b int64) int64 {
	for b != 0 {
		a, b = b, a%b
	}
	if a < 0 {
		return -a
	}
	return a
}

func collatz(n int64) int64 {
	steps := int64(0)
	for n > 1 {
		if n%2 == 0 {
			n /= 2
		} else {
			n = 3*n + 1
		}
		steps++
	}
	return steps
}

func sumOdd(n int64) int64 {
	var s int64
	for i := int64(0); i < n; i++ {
		if i%2 == 0 {
			continue
		}
		s += i
	}
	return s
}

func norm(x float64, y float64) float64 {
	return math.Sqrt(x*x + y*y)
}

func main() {}
