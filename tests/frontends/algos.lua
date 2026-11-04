-- Lua 5.4: // and % floor, / is float division
function gcd(a, b)
  while b ~= 0 do
    a, b = b, a % b
  end
  return math.abs(a)
end

local function collatz(n)
  local steps = 0
  while n > 1 do
    if n % 2 == 0 then
      n = n // 2
    else
      n = 3 * n + 1
    end
    steps = steps + 1
  end
  return steps
end

function sum_down(n)
  local s = 0
  for i = n, 1, -1 do
    s = s + i
  end
  return s
end

function avg(a, b)
  return (a + b) / 2
end

function count_until(n)
  local i = 0
  repeat
    i = i + 1
  until i * i >= n
  return i
end
