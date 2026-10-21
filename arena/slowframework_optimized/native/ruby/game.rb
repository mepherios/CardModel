def combo_bonus__sum_1_to_n_closed_form(hits)
  if (hits <= (0))
    return (0)
  end
  return ((hits * (hits + (1))) / (2))
end

def combo_bonus(hits)
  return ((5) * combo_bonus__sum_1_to_n_closed_form(hits))
end

def damage(attack, defense, crit)
  base = 0
  base = (((attack * (2)) + (0)) - defense)
  if (base < (1))
    base = (1)
  end
  if crit
    return (base * (2))
  end
  return base
end

def distance_sq(x1, y1, x2, y2)
  return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))
end

def in_range(x1, y1, x2, y2, radius)
  return (distance_sq(x1, y1, x2, y2) <= (radius * radius))
end

def lerp(a, b, t)
  return (a + ((b - a) * t))
end

def xp_for_level__sum_of_squares_closed_form(level)
  if (level <= (0))
    return (0)
  end
  return (((level * (level + (1))) * (((2) * level) + (1))) / (6))
end

def xp_for_level(level)
  return ((10) * xp_for_level__sum_of_squares_closed_form(level))
end

def level_from_xp(xp)
  level = 0
  level = (0)
  while (xp_for_level((level + (1))) <= xp)
    level = (level + (1))
  end
  return level
end

def next_seed(seed)
  return (((seed * (1103515245)) + (12345)) % (2147483648))
end

def tiles_in_circle(r)
  count = 0
  x = 0
  cm_it1 = 0
  cm_stop2 = 0
  y = 0
  cm_it3 = 0
  cm_stop4 = 0
  count = (0)
  cm_it1 = (-r)
  cm_stop2 = (r + (1))
  while (cm_it1 < cm_stop2)
    x = cm_it1
    cm_it1 = (cm_it1 + (1))
    cm_it3 = (-r)
    cm_stop4 = (r + (1))
    while (cm_it3 < cm_stop4)
      y = cm_it3
      cm_it3 = (cm_it3 + (1))
      if (((x * x) + (y * y)) <= (r * r))
        count = (count + (1))
      end
    end
  end
  return count
end

def trajectory_y(a, b, c, d, t)
  return ((((a * (t ** (3))) + (b * (t ** (2)))) + (c * t)) + d)
end
