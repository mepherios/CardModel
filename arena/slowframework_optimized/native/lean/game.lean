namespace CM

partial def combo_bonus__sum_1_to_n_closed_form (hits : Int) : Int := Id.run do
  if (decide (hits <= (0 : Int))) then
    return (0 : Int)
  return (Int.fdiv (hits * (hits + (1 : Int))) (2 : Int))


partial def combo_bonus (hits : Int) : Int := Id.run do
  return ((5 : Int) * (combo_bonus__sum_1_to_n_closed_form hits))

end CM

namespace CM

partial def damage (attack : Int) (defense : Int) (crit : Bool) : Int := Id.run do
  let mut base : Int := 0
  base := (((attack * (2 : Int)) + (0 : Int)) - defense)
  if (decide (base < (1 : Int))) then
    base := (1 : Int)
  if crit then
    return (base * (2 : Int))
  return base

end CM

namespace CM

partial def distance_sq (x1 : Int) (y1 : Int) (x2 : Int) (y2 : Int) : Int := Id.run do
  return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))

end CM

namespace CM

partial def in_range (x1 : Int) (y1 : Int) (x2 : Int) (y2 : Int) (radius : Int) : Bool := Id.run do
  return (decide ((distance_sq x1 y1 x2 y2) <= (radius * radius)))

end CM

namespace CM

partial def xp_for_level__sum_of_squares_closed_form (level : Int) : Int := Id.run do
  if (decide (level <= (0 : Int))) then
    return (0 : Int)
  return (Int.fdiv ((level * (level + (1 : Int))) * (((2 : Int) * level) + (1 : Int))) (6 : Int))


partial def xp_for_level (level : Int) : Int := Id.run do
  return ((10 : Int) * (xp_for_level__sum_of_squares_closed_form level))


partial def level_from_xp (xp : Int) : Int := Id.run do
  let mut level : Int := 0
  level := (0 : Int)
  while (decide ((xp_for_level (level + (1 : Int))) <= xp)) do
    level := (level + (1 : Int))
  return level

end CM

namespace CM

partial def next_seed (seed : Int) : Int := Id.run do
  return (Int.fmod ((seed * (1103515245 : Int)) + (12345 : Int)) (2147483648 : Int))

end CM

namespace CM

partial def tiles_in_circle (r : Int) : Int := Id.run do
  let mut count : Int := 0
  let mut x : Int := 0
  let mut cm_it1 : Int := 0
  let mut cm_stop2 : Int := 0
  let mut y : Int := 0
  let mut cm_it3 : Int := 0
  let mut cm_stop4 : Int := 0
  count := (0 : Int)
  cm_it1 := (-r)
  cm_stop2 := (r + (1 : Int))
  while (decide (cm_it1 < cm_stop2)) do
    x := cm_it1
    cm_it1 := (cm_it1 + (1 : Int))
    cm_it3 := (-r)
    cm_stop4 := (r + (1 : Int))
    while (decide (cm_it3 < cm_stop4)) do
      y := cm_it3
      cm_it3 := (cm_it3 + (1 : Int))
      if (decide (((x * x) + (y * y)) <= (r * r))) then
        count := (count + (1 : Int))
  return count

end CM

namespace CM

partial def trajectory_y (a : Int) (b : Int) (c : Int) (d : Int) (t : Int) : Int := Id.run do
  return ((((a * (t ^ ((3 : Int)).toNat)) + (b * (t ^ ((2 : Int)).toNat))) + (c * t)) + d)

end CM
