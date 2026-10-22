// A small engine-style math header written for the card model's tests: the shapes Unreal Engine's math uses
// (a templated vector with an anonymous union, static and member functions, operators, a const reference
// clamp, a branch with an early return, a float/double mix, an out parameter, a read at an index the inputs
// choose), so the frontend, the lifter, the
// canonical forms and the witness can be checked without an engine install. It is not engine code.
#pragma once
#include <cmath>
#include <cstdint>

namespace Mini {

template<typename T>
struct TVec
{
	union
	{
		struct
		{
			T X;
			T Y;
			T Z;
		};
		T XYZ[3];
	};

	TVec() {}
	TVec(T InX, T InY, T InZ) : X(InX), Y(InY), Z(InZ) {}

	static T Dot(const TVec& A, const TVec& B) { return A.X * B.X + A.Y * B.Y + A.Z * B.Z; }
	static T DotSwapped(const TVec& A, const TVec& B) { return B.Z * A.Z + (B.Y * A.Y + B.X * A.X); }
	T operator|(const TVec& V) const { return X * V.X + Y * V.Y + Z * V.Z; }
	T SizeSquared() const { return X * X + Y * Y + Z * Z; }
	T Size() const { return std::sqrt(SizeSquared()); }
	T Component(int32_t Index) const { return XYZ[Index]; }
	void SetComponent(int32_t Index, T Value) { XYZ[Index] = Value; }

	static TVec Cross(const TVec& A, const TVec& B)
	{
		return TVec(A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X);
	}

	TVec operator+(const TVec& V) const { return TVec(X + V.X, Y + V.Y, Z + V.Z); }
	TVec operator*(T Scale) const { return TVec(X * Scale, Y * Scale, Z * Scale); }
	TVec& operator+=(const TVec& V) { X += V.X; Y += V.Y; Z += V.Z; return *this; }

	TVec GetSafeNormal(T Tolerance = T(1e-8)) const
	{
		const T Square = SizeSquared();
		if (Square < Tolerance)
		{
			return TVec(0, 0, 0);
		}
		const T Scale = T(1) / std::sqrt(Square);
		return TVec(X * Scale, Y * Scale, Z * Scale);
	}

	void ToDirectionAndLength(TVec& OutDir, float& OutLength) const
	{
		OutLength = (float)Size();
		if (OutLength > 1e-8f)
		{
			OutDir = *this * (T(1) / OutLength);
		}
		else
		{
			OutDir = TVec(0, 0, 0);
		}
	}
};

struct MathLite
{
	template<class T>
	static const T& Max(const T& A, const T& B) { return A < B ? B : A; }

	template<class T>
	static T Clamp(const T X, const T Lo, const T Hi) { return X < Lo ? Lo : (X < Hi ? X : Hi); }

	static float Lerp(float A, float B, float Alpha) { return A + Alpha * (B - A); }
	static double LerpStable(double A, double B, double Alpha) { return A * (1.0 - Alpha) + B * Alpha; }

	static uint32_t Hash(uint32_t A) { return A * 2654435761u + 1013904223u; }

	// an early return, then writes to locals (dead once returned) and to an out parameter (seen after it)
	static double EarlyOut(double X, double& Out)
	{
		Out = 1.0;
		if (X < 0.0)
		{
			return -1.0;
		}
		double T = X * 2.0;
		T = T * T + 1.0;
		T = T * T + 1.0;
		Out = T;
		return T + X;
	}

	// the sign bit read through a same-width signed conversion (Float16's test): not value-preserving
	static bool SignBitSet(uint16_t Encoded) { return (int16_t)Encoded < 0; }

	// a shift by a count the inputs choose (C++ defines it for 0..31 here), and a constant one of a 64-bit value
	static uint32_t Bit(uint32_t N) { return 1u << N; }
	static uint64_t High(uint64_t X) { return X >> 56; }

	// a read through an index the inputs choose: C++ defines it for 0, 1 and 2 only
	static double Pick3(double A, double B, double C, int32_t I)
	{
		const double V[3] = {A, B, C};
		return V[I];
	}

	static double SmoothStep(double A, double B, double X)
	{
		if (X < A)
		{
			return 0.0;
		}
		if (X >= B)
		{
			return 1.0;
		}
		const double T = (X - A) / (B - A);
		return T * T * (3.0 - 2.0 * T);
	}
};

template struct TVec<double>;

inline void Instantiate()
{
	double d = 0;
	(void)MathLite::Clamp(d, d, d);
	(void)MathLite::Max(d, d);
}

}  // namespace Mini
