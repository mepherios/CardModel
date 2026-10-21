function combo_bonus__sum_1_to_n_closed_form(hits)
  if (hits <= (0)) then
    return (0)
  end
  return ((hits * (hits + (1))) // (2))
end

function combo_bonus(hits)
  return ((5) * combo_bonus__sum_1_to_n_closed_form(hits))
end

function damage(attack, defense, crit)
  local base = 0
  base = (((attack * (2)) + (0)) - defense)
  if (base < (1)) then
    base = (1)
  end
  if crit then
    return (base * (2))
  end
  return base
end

function distance_sq(x1, y1, x2, y2)
  return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))
end

function in_range(x1, y1, x2, y2, radius)
  return (distance_sq(x1, y1, x2, y2) <= (radius * radius))
end

function lerp(a, b, t)
  return (a + ((b - a) * t))
end

function xp_for_level__sum_of_squares_closed_form(level)
  if (level <= (0)) then
    return (0)
  end
  return (((level * (level + (1))) * (((2) * level) + (1))) // (6))
end

function xp_for_level(level)
  return ((10) * xp_for_level__sum_of_squares_closed_form(level))
end

function level_from_xp(xp)
  local level = 0
  level = (0)
  while (xp_for_level((level + (1))) <= xp) do
    level = (level + (1))
    ::cm_continue_1::
  end
  return level
end

function next_seed(seed)
  return (((seed * (1103515245)) + (12345)) % (2147483648))
end

function tiles_in_circle(r)
  local count = 0
  local x = 0
  local cm_it1 = 0
  local cm_stop2 = 0
  local y = 0
  local cm_it3 = 0
  local cm_stop4 = 0
  count = (0)
  cm_it1 = (-r)
  cm_stop2 = (r + (1))
  while (cm_it1 < cm_stop2) do
    x = cm_it1
    cm_it1 = (cm_it1 + (1))
    cm_it3 = (-r)
    cm_stop4 = (r + (1))
    while (cm_it3 < cm_stop4) do
      y = cm_it3
      cm_it3 = (cm_it3 + (1))
      if (((x * x) + (y * y)) <= (r * r)) then
        count = (count + (1))
      end
      ::cm_continue_2::
    end
    ::cm_continue_1::
  end
  return count
end

function cm_ipow(a, b)
  local r = 1
  while b > 0 do
    if b % 2 == 1 then r = r * a end
    b = b // 2
    if b > 0 then a = a * a end
  end
  return r
end
function trajectory_y(a, b, c, d, t)
  return ((((a * cm_ipow(t, (3))) + (b * cm_ipow(t, (2)))) + (c * t)) + d)
end
