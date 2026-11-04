# ENVIRONMENTS: the running machine as mathematics

The user (2026-11-04): *"Math for GPU vs CPU and running environments, so that DirectX and different GPU
structures, RAM environments, drivers etc. and their fundamental structures and interaction models are something
we also need. Ensure our model's capabilities for transference from the generator (the current running system) to
the running system have complete understanding of the computational structure and the physical capabilities, and a
card model structure that can handle and scale these things accordingly. Find all such problems our model
currently does not handle but needs to, with our card math as needed."*

Written from `main` at 4a8fab8. [FOUNDATIONS.md](FOUNDATIONS.md) D14 says a target language, with its compiler,
flags and device, is a Σ-algebra M_L, and a translation is correct where M_L agrees with the model M. Today the
"device" part of that sentence is implicit: a target is `c@O2` or `rust@release` *on the host the model runs on*.
This document makes the device explicit. The machine that generates a program (the **generator** G) and the machine
that runs it (the **runner** R) are two environments, each a model of the theory in the sense of D14, and carrying
a program from G to R is sound exactly where their models agree. Everything a GPU, a memory hierarchy, a driver or
a graphics API adds to the picture is one of three things: new **atoms of the signature** (sorts and op cards), a
new **model with its divergence laws**, or a **measurement** that fixes a cost. §2 states those three forms as
definitions. §3 is the catalogue of what the model does not handle today, each gap with its card-math form. §4 has
what was measured on this host while writing, §5 says which gaps are measurable now, which need a device in reach,
and which are conjecture, and §6 is the order of work. Nothing here changes behaviour; it is the plan the
environment workstream follows, and the rule for how any new device enters.

## 1. What already counts, and what it gives this plan

| exists today | where | what it gives |
|---|---|---|
| targets are models, with divergence laws | FOUNDATIONS D14, A6; [ANALYSE.md](ANALYSE.md) and its 12 laws (`int_width` … `float_assoc`); runner variants `c@O0`, `c@O2`, `c@fastmath`, `c@ubsan`, `rust@debug`, … in `engines/analyse.py` (`VARIANTS`) | the exact form every environment difference takes: a law "M_R(op) ≠ M(op) iff cond", fired by the instrumented reference and witnessed per runner. ANALYSE already records one *device* difference (⌊a/0⌋ traps on x86-64 and gives 0 on ARM64) as a per-runner row |
| costs are measured on the host, never assumed | CM09; metric cards (`cards/metric/metric__ADD__native`: median, MAD, samples, seed, inputs signature, a host block) | the shape of a per-machine measurement card. Its host block holds `machine`, `system`, `python`, `node`: no cores, SIMD extensions, caches, GPU or driver (E21) |
| hardware as cards: an ISA is its instruction cards, a console is its hardware cards | [MACHINES.md](MACHINES.md): `isa/lr35902`, `isa/armv5te`, `hardware/gb_ppu`, `hardware/nds_3d`, `hardware/nds_vram`, `hardware/nds_dma`, `machine/gameboy`, `machine/nds` (CM32) | the existence proof. A fixed-function GPU (the NDS 3D engine), VRAM banks and DMA are already cards with registers, timing and behaviour. A modern GPU is the same method with three differences: it is programmable, it is reached through a driver rather than owned registers, and its parallel execution model has no counterpart in the LR35902 cards |
| a GPU ISA decoded, with translation gaps named | [ANYPS5.md](ANYPS5.md): RDNA 1/2 instructions over AMD's list, "decoded" kept apart from "translated correctly" | the honesty rule for GPU instruction cards: a decoded instruction is not a translated one until its semantics is a card with vectors |
| SIMD versus scalar as two builds of one truth | [UNREAL.md](UNREAL.md): the engine's scalar FPU path is *truth*, the NEON build is *shipped*, `-ffp-contract=off` as the engine's own Mac build sets it | the pattern for E1 and E12: the vector form is a model of the scalar form, checked by running, with contraction as a named flag |
| the platform card and the effect shell | `cards/platform/macos` (bundle, frameworks, shell compile line), CM21, CM34; ROADMAP Phase I (iPadOS as the test of "native") | where the OS, driver and API surface of a runner belongs: boundary cards of a platform card (E19) |
| the scaling plan's rows for the spectrum and the interaction model | [SCALING.md](SCALING.md) §4.5 (concurrency and memory-model cards), §4.6 (f16, bf16, f32, rounding modes, fused ops), §4.7 (host, device, capability and reach cards) | the slots this document fills in. §4.5's memory-model cards are E3; §4.7's host and device cards are E21. Not redone here, cross-referenced |
| device runners as a milestone | ROADMAP Phase J4 (the same function on ARM64, x86-64, iPadOS, through the model's own backend) | E22's witness tier: a difference between devices is *witnessed* only when both devices ran it |
| the Gödel layer: atoms take primes forever, content is a homomorphism, carry-over has a gap | FOUNDATIONS D11–D13; docs/GODEL.md §4 (PR #20); docs/GODEL_AUDIT.md (PR #25); CM43, CM45 | what transfers for free between devices (content) and what does not (arrangement, schedule, cost), §3.5 |
| the fixed-width type series | MATH_CORE F3 and §4 (BV(w), memory as BV(a) → BV(8)); FOUNDATIONS F6 (binary32 as a sort of its own, not F32 rounding binary64); the foundations workstream is building the fixed-width int and f32 series now | E11 depends on it and adds f16 and bf16 to the same series, not a second mechanism |

## 2. Definitions (proposed, continuing FOUNDATIONS.md's numbering)

**D15. Environment.** An environment is a tuple D = (ISA and its extensions, microarchitecture, memory hierarchy,
accelerators, numeric model, operating system, driver and API versions, limits, permissions). Each component is a
card or a value on a card. The generator G is the environment the model runs in; the runner R is the one a
program is shipped to. The model measures G's card itself. R's card is measured when R is in reach, and otherwise
*declared* from its documentation, which is a lower tier (D10) and is marked as such on every claim that uses it.

**D16. Device theories and device models.** A device family presents a theory T_D: its sorts (lanes, vectors,
address spaces, queues), its ops (instructions, or API calls, as op cards with `ir.types`, `eval`, `domain`,
`emit`) and its laws. A physical device with a given driver is a model M_D of T_D, and also, through the op cards
it implements, a Σ-algebra in the sense of D14. The correctness domain of a transfer is where M_D agrees with M;
its edge is a set of **divergence laws**, written and witnessed as ANALYSE.md's laws are. A software implementation
of the same API (Mesa's lavapipe for Vulkan, WARP for Direct3D 12) is another model of T_D, cheap to run, and its
agreement with the hardware model is sampled, never assumed.

**D17. Capability cards are hypotheses.** A capability card is a finite map from capability names (`warp_size`,
`l1d_bytes`, `f16_arith`, `denorm_f32`, `max_workgroup`, `watchdog_s`, …) to values, each with the tier of its
evidence: measured on that device, declared from its documentation, or unknown. D5 already makes every law a
*conditional* equation H(x̄) → l = r. A capability enters the mathematics as a conjunct of H: a subgroup reduction
is equal to a particular tree sum under the hypothesis `subgroup_size = 32`, a fused multiply-add is one rounding
under `fma = true`, a kernel finishes under `steps ≤ watchdog`. A law instantiated on a device whose card does not
satisfy its hypothesis does not fire, which is A3 (laws are sorted) extended from sorts to capabilities.

**D18. The transfer judgment.** carry(t, G, R) takes a canonical term t with its certificate (D8) and the two
environment cards, and produces a **transfer card** with: the atoms of t and of its certificate that R's signature
lacks (the gap of the carry-over, D13); the divergence laws of M_R that fire inside t's declared domain (latent
flaws, in ANALYSE's sense, now with a device axis); the laws of the certificate whose hypotheses R's card does not
satisfy (an optimization that was a rewrite on G and is not one on R); and the predicted cost of t on R from R's
cost vectors, with the tier of those vectors. Its verdict is *carried* (witnessed on R), *predicted* (from cards
only) or *refused* (a gap or a firing with no fix). A program that is carried has, by this definition, been
understood against the runner's computational structure and physical capabilities, because every claim about it
names the card and the tier it rests on.

**A8. Environments are models.** A difference between the generator and a runner is a divergence law of M_R, a
missing atom in the carry-over, or a hypothesis of a law that R's card does not satisfy. Codegen for a device
never contains a per-device patch that silently changes meaning (A6, CM16, extended from languages to devices).

## 3. The gaps

Each gap gives what the model has today, what it needs, the card-math form it takes, and its evidence tier (§5).
They are proposed as gap cards, numbered from the registry at adoption.

### 3.1 Execution models

**E1. SIMD on the CPU: lanes as a sort.** *Today:* the IR has no vector type; vectorization happens inside the C,
Rust and Swift compilers, invisibly, and the only trace of it is the `float_assoc` law. *Needed:* vectors V(n, s) of
n lanes of sort s as sorts (n from the device card: 4 × f32 for SSE and NEON, 8 for AVX, scalable for SVE), with
lane-wise op cards, shuffles, masks, and horizontal reductions. *Card math:* the lane-wise law `V_op(v, w) =
map₂(op, v, w)` is a theorem card per op, so a vectorization is a *rewrite with a certificate* (D8) and not a thing
the C compiler may or may not do. SSE, AVX, NEON and SVE instruction cards enter exactly as `isa/armv5te`'s do, as
instruction cards with encodings, timing and semantics in the card language. A horizontal float reduction is
*not* lane-wise, and its tree is part of its meaning (E14). *Evidence:* measurable today on this host (AVX, FMA,
F16C in `lscpu`), §4.

**E2. SIMT: warps, workgroups and grids.** *Today:* nothing. The IR is sequential; `parallel-for` is a planned
construct (SCALING §4.5). *Needed:* a kernel is a function of a thread index (ℤ³ → effects on arrays) run over a
grid; a workgroup shares memory and barriers; a subgroup (warp of 32 on NVIDIA and Apple, wavefront of 32 or 64 on
AMD, 8 to 32 on Intel) executes in lockstep. *Card math:* `launch(k, grid)` is an op whose semantics is the
parallel composition of `k(i)` for every `i`, under the obligation that the `k(i)` are independent (no two write
one location, no read of another's write without a barrier). That obligation is a logic obligation with a path
condition, in the same form as ANALYSE's partial-op obligations: *proved* (disjoint index sets by interval
analysis), *sampled* (a seeded scheduler found no race, SCALING §4.5) or *open* with a counterexample. A branch
inside a subgroup executes both arms under masks, so `IF_EXPR` on SIMT has a cost of `cost(then) + cost(else)`,
not `max`, which is a device-dependent cost law, and a barrier under a divergent condition is undefined, which
is an obligation "barrier is reached under a subgroup-uniform condition". The subgroup size is a hypothesis
(D17): a term with a subgroup shuffle or ballot has one meaning per `subgroup_size`, so it is carried only to a
device whose card satisfies that hypothesis, or it is rewritten to a size-independent form with a certificate.
*Evidence:* conjecture until a device or a software Vulkan runs a kernel (E17).

**E3. Threads, cores and memory consistency on the CPU.** SCALING §4.5 owns this (threads, atomics with
orderings, locks, memory-model cards for C11, the Linux kernel and the ISA). What transfer adds: a memory-model
card is a *set of equations that stop holding*. Under x86-TSO a store followed by a load to another address may
reorder, and under ARM's weaker model loads reorder too, so a two-thread term that is equal to its sequential
reading on x86 is not on ARM64. That is a divergence law `memory_order` with a per-ISA row, fired on terms with
two or more threads and an unordered access, and the fix is the same as ANALYSE's: declare the ordering (an
`acquire`/`release` hypothesis) or change the code. *Evidence:* conjecture; a litmus runner (the seeded scheduler)
makes it sampled.

**E4. Two programs, one computation: the host side of a device program.** *Today:* nothing. *Needed:* a GPU
program is a CPU program that allocates, uploads, records commands, submits them to a queue, waits on fences and
reads back, together with the kernels the queue executes. *Card math:* the queue is a boundary (CM21) whose effects
carry a happens-before partial order (submit < execute < fence signalled < read-back valid). ROADMAP J5's trace
model, which tells two programs apart by the order and number of their effects, is the right model, extended with
that order: a read-back before its fence is an obligation that fails, and a resource used in two queued commands
without a barrier is a race in E2's sense. A "pipeline" (shader stages, resource states, descriptor layouts) is
data on the API card (E16) that the host program must set consistently, so each consistency rule (a D3D12
resource state transition, a Vulkan image layout) is one more obligation, checked statically where the term
decides it and sampled otherwise. *Evidence:* conjecture; the obligations are checkable on a software API model.

**E5. Watchdogs and budgets per device.** *Today:* `deep_recursion` (depth ≥ 400) and `step_budget` (300,000
steps) are laws with one host-shaped constant each. *Needed:* a device kills a kernel after a wall-clock budget
(Windows TDR about 2 s, iOS and macOS on a hung command buffer) and a phone throttles after seconds of sustained
load, so a function that is fine on the generator is cut on the runner. *Card math:* the constants become
capability values (`watchdog_s`, `stack_bytes`, `sustained_fraction`) and the laws keep their form with the value
read from R's card; `step_budget` fires per device. *Evidence:* measurable with a device; declared from
documentation before that.

### 3.2 Memory models

**E6. The memory hierarchy, and why the additive cost model stops there.** *Today:* a cost c : Σ → ℝ≥0, additive
over the term (D7), with per-op anchors measured on the host. That is right for scalar terms and wrong for anything
that touches an array: the cost of `LOAD` is not a number but a function of where the address is in the hierarchy,
and that depends on the term's whole access history. *Needed:* a **memory-level card** per level of each
environment (registers, L1, L2, L3, RAM, VRAM, workgroup-shared, constant, texture), each with size, line size,
latency and bandwidth, *measured* (a pointer chase and a streaming copy are the two probes; §4 has the chase on
this host). *Card math:* cost(t) = Σ_op c(op) + Σ_access c_level(access), where the level is assigned by a cache
model of the trace. The cache model is a predictor and carries tier *bounded*, never *proof*: it is used to rank
candidates, and the choice is confirmed by measurement on the device (CM09) before it is claimed. A loop
interchange, a tiling or a blocking is a rewrite (its certificate is the loop-reordering theorem under the
independence obligation of E2) whose *benefit* is predicted by the hierarchy card and witnessed by the metric
card. *Evidence:* measurable today for the CPU side, §4.

**E7. Host and device memory: the transfer is an op with a cost.** *Today:* nothing. *Needed:* uploads and
read-backs as boundary ops with measured bandwidth and latency (PCIe for a discrete GPU, nothing for Apple's
unified memory, where the same bytes are visible to both and the "transfer" is a cache flush). *Card math:* the
break-even equation is a theorem over the two cards: moving work to the device pays when `bytes_up / bw_up +
bytes_down / bw_down + launch_latency < time_cpu − time_gpu`, and the roofline bound `time ≥ max(flops /
peak_flops, bytes / peak_bw)` is a lower bound the predicted cost cannot go under. Both are *bounded*-tier claims
computed from capability values, and they become *measured* when the transfer ran. *Evidence:* measurable with a
device; this host has no GPU (no `/dev/dri`), so it is predicted here and measured on the user's Mac.

**E8. Layout, alignment and endianness.** *Today:* machine arrays of `u8` and `int` with no declared layout;
list types with no layout at all. *Needed:* a layout is a function from an element index to a byte offset, with
an alignment per sort per device (an unaligned 8-byte load is a fault on some ISAs and merely slow on x86-64; a
uniform buffer offset must be a multiple of `minUniformBufferOffsetAlignment`, 256 bytes on some GPUs and 16 on
others; `std140` pads a `vec3` to 16 bytes). *Card math:* alignment is a divergence-law family like `int_width`
(`unaligned_access`: fault, slow or fine, per ISA row), with its obligation proved by the layout or sampled. A
change of layout, array-of-structures to structure-of-arrays, is a rewrite that preserves γ *by construction*,
since content forgets arrangement (D11): the Gödel content of a term and of its relaid-out form is the same
vector, and what the rewrite changes is exactly what the structure code (D12) sees. Endianness is one value on
the ISA card and a hypothesis of every byte-level law.
*Evidence:* measurable today on the CPU side; declared for GPU API limits.

**E9. Address spaces and pointers.** *Today:* the IR has no pointers (SCALING §2), and memory is planned as one
array BV(a) → BV(8) (MATH_CORE §4). *Needed:* a GPU has several disjoint memories (global, workgroup-shared,
private, constant, texture) and a pointer is a pair (space, offset). *Card math:* one array per address space,
each a sort, with `LOAD`/`STORE` ranked per space; a cast between spaces is an op with an empty domain on devices
that forbid it, which makes "this kernel keeps its data in shared memory" a sort fact rather than a comment.
Aliasing between two accesses is an obligation in E2's family. *Evidence:* conjecture; falls out of MATH_CORE's
memory sort when it lands.

**E10. Residency.** VRAM is smaller than RAM, and a working set larger than it is paged or refused by the
driver. *Card math:* `bytes_resident ≤ vram_bytes` is an obligation with a capability hypothesis; its failure on a
smaller runner is a transfer-card refusal, not a slowdown discovered in the field. *Evidence:* declared.

### 3.3 Numeric models

**E11. f32, f16, bf16 (and tf32) as sorts.** *Today:* `float` is binary64 only; `F32`, `F32_BITS`, `BITS_F32`
round through binary64 (FOUNDATIONS F6); the fixed-width series under construction adds binary32 as a sort.
*Needed:* binary16 (IEEE), bfloat16 (binary32 with the low 16 bits of the significand dropped) and tf32 (10
significand bits, used inside tensor units) as sorts of the same series, each with its own ranks of the arithmetic
ops, with conversion ops whose `eval` is the exact rounding, and with the laws that *fail* between them stated:
rounding is not a homomorphism (`f16(a + b) ≠ f16(a) + f16(b)` in general), which is precisely the divergence
content of a lower-precision device. *Card math:* one type series, one op card per op with one rank per
precision, a `precision_loss` law fired when a term is carried to a device whose arithmetic sort is narrower than
the term's. *Evidence:* measurable today for f16 conversion (this host has F16C, §4); bf16 and tf32 arithmetic
need a device, and their `eval` is exact arithmetic in Python meanwhile (A2: one model, named).

**E12. Contraction, rounding and accuracy bounds per op per device.** *Today:* `MULADD` has a Rust FMA form with a
note; `float_assoc` names `-ffast-math`; UNREAL pins `-ffp-contract=off`. *Needed:* a **numeric-model card** per
device and compiler mode listing, for every float op, whether it is correctly rounded (add, mul, fma, usually div
and sqrt on CUDA, not in graphics shaders), its maximum error in ULP when it is not (the Vulkan specification
bounds each SPIR-V op; vendor fast paths such as NVIDIA's MUFU and every shading language's `fast::` namespace
are looser), whether contraction of `a * b + c` into one rounding is allowed (gcc 13 contracts by default, §4;
Metal compiles with fast math on by default; HLSL's `precise` turns it off per variable), and the rounding mode.
*Card math:* a correctly rounded op is a *proof*-tier equality with M's op at that sort; an op with a ULP bound
is a *bounded*-tier claim, `|M_D(op)(x) − M(op)(x)| ≤ k · ulp`, which is exactly the tier CM46 provides and
nothing stronger; contraction is a divergence law `fp_contract` ("`MULADD` ≠ `ADD(MUL)` iff contraction on"),
fired on every `a * b ± c`. The e-graph fires a float law only when the numeric-model card of the target
satisfies its hypothesis (D17): commutativity everywhere, associativity nowhere, `x * 1 = x` everywhere but
`x * 0 = 0` only without NaN and infinities. *Evidence:* measurable today on the CPU (§4: a two-rounding and a
one-rounding result differ at the 2⁻⁵⁴ place); per-GPU bounds declared from the specifications until a device
runs the probe suite.

**E13. Denormals, NaN payloads and signed zero.** *Today:* nothing fires on a denormal. *Needed:* most GPUs
flush binary32 denormals to zero in graphics shaders (Vulkan exposes `shaderDenormFlushToZeroFloat32` and
`shaderDenormPreserveFloat32` per device), CUDA preserves them unless `-ftz=true`, and `-Ofast` on x86-64 sets
FTZ and DAZ in MXCSR for the whole process (§4: 5 × 10⁻³¹⁰ × 0.5 is 0, and the input is no longer classified
subnormal). *Card math:* a divergence law `denormal_flush` ("a result or an operand in (0, 2⁻¹²⁶) becomes 0 iff
`denorm = flush`") with per-device rows read from the capability card; NaN payload propagation and the sign of
zero are two more laws of the same shape, both with "implementation-defined" as one of the rows. *Evidence:*
witnessed today on this host for the CPU; declared per GPU.

**E14. Reduction order: when the same program has two answers on one device.** *Today:* `float_assoc` says
`-ffast-math` reassociates. *Needed:* on a device, a parallel float sum has no fixed tree unless the program
fixes it: a vectorized reduction sums `n` interleaved partial sums, so its answer depends on the lane count of
the *runner* (§4: the same C source, same host, gives 136,599,666,688 scalar and 136,599,740,416 vectorized), and
an atomic float accumulation across workgroups depends on the schedule, so two runs on one GPU differ. *Card
math:* a reduction op card carries its tree as part of its meaning (`SUM_seq`, `SUM_tree(k)`, `SUM_atomic`); the
first two are deterministic and equal to each other only over `int`; the third has no value in M, only a
*distribution*, so a term that uses it has a sample-tier identity and the transfer card says so. The fix the
model offers is a rewrite to a fixed tree with a certificate of determinism, at a measured cost. *Evidence:*
measurable today on the CPU (lane count); with a device for the atomic case.

**E15. Integers on a GPU.** *Today:* `int` is ℤ, and `int_width` has per-language rows. *Needed:* a GPU computes
in 32 bits natively, emulates 64-bit integers in several instructions, and divides slowly (an emulated sequence of
tens of instructions). Overflow wraps in SPIR-V, is undefined on paper in the Metal Shading Language (it is
C++), and `shift_count` and `float_to_int` have their own rows (Direct3D saturates and maps NaN to 0; SPIR-V
leaves the out-of-range conversion undefined). *Card math:* the same twelve laws of ANALYSE.md with a row per
shading language and per device, and BV(32) as the default integer sort of a kernel (MATH_CORE F3); the cost
vector of `DIV` on a GPU is a measured anchor like every other (CM09), so a `DIV` by a constant is rewritten to a
multiply-and-shift *there* and left alone on the CPU, each with its certificate. *Evidence:* declared until a
device or software runner witnesses the rows.

### 3.4 Drivers and API surfaces as models

**E16. The APIs are presentations of one theory.** *Today:* nothing, beyond the macOS platform card's framework
list. *Needed:* Direct3D 12, Vulkan, Metal, CUDA, OpenCL and WebGPU each offer the same ten or so operations
(create a device, allocate memory, create a buffer or image, compile a shader, build a pipeline, record commands,
dispatch or draw, barrier, submit, fence, map) under different names and with different side conditions. *Card
math:* an abstract **device theory** T_dev with those ops as op cards; each API is an **API card** whose
interpretation maps every T_dev op to a call sequence (its `emit` template, as a language card's templates do
today), and the map is a carry-over in D13's sense: a homomorphism on content, with the atoms that have no image
named as the gap (Vulkan's push constants, Direct3D's root constants and Metal's `setBytes` are one atom with
three images; Metal's argument buffers and Vulkan's descriptor sets are two atoms whose images only partly
overlap). The matrix (`cardmodel matrix`, [ROADMAP.md](ROADMAP.md) §2) then has an API axis: every cell is the same T_dev term,
emitted through two API cards, run, and compared. *Evidence:* the theory and the API cards are writable today; a
cell runs only on a device or a software model (E17).

**E17. Shading languages and device IRs are codegen targets, and a CPU implementation witnesses them.**
*Today:* language cards for 24 languages with `emit` templates per op card and conformance by running
(TRANSLATE_REAL_PROGRAMS.md). *Needed:* HLSL, GLSL, MSL, WGSL, SPIR-V and PTX as language cards of the same
shape. SPIR-V first: it is a specified IR with a validator, its ops map one-to-one onto op cards, and ANYPS5's
RDNA decoder already sits on the far side of it. WGSL second, because WebGPU implementations run it on every OS.
*Card math:* a shading language is M_L in D14 with the numeric-model card of E12 as its float semantics, and
nothing else is new. The witness is the part that matters for a generator with no GPU: Mesa's lavapipe (Vulkan on
the CPU) and Microsoft's WARP (Direct3D 12 on the CPU) are *models of the API* that a CI job can run, so the
conformance cells of every op card at every numeric sort, and the divergence-law firings, are witnessed without
hardware, labelled with the software model's fingerprint and never confused with the hardware's. They enter as
probed toolchains (CM01: used when present, never required). *Evidence:* measurable as soon as the CI image has
Mesa; this host has neither `vulkaninfo` nor a Vulkan loader today, so the tier here is predicted.

**E18. Drivers version the model.** *Today:* a metric card's host block has no driver. *Needed:* the same API on
the same silicon behaves differently across driver versions (shader compiler changes, fast paths, bugs), so a
device model is M_(device, driver, API version), not M_device. *Card math:* every witness, metric and transfer
card carries the full fingerprint (vendor id, device id, driver version, API version, OS build) the way CM09
requires the host fingerprint today, and J2's rule applies: a law whose prediction a driver contradicts is a flaw
card of its own (rea-cards' `re_flaw`), attached to that fingerprint, so a "known driver bug" is a card with a
witness rather than folklore. *Evidence:* the card shape is writable today; the rows need devices.

**E19. The OS surface of the runner.** *Today:* one platform card (macOS); Phase I's audit lists what a shipped
program may not depend on. *Needed:* a platform card per OS (Windows, Linux, iPadOS, Android) whose boundary cards
say how a program reaches the GPU (the loader it may `dlopen`, static linking, the sandbox's rules, whether code
generation is allowed at run time; iOS forbids JIT, which is why Phase I5 is the model's own ahead-of-time
backend), what the window system is, and which permissions a device needs (CM34). *Card math:* each boundary card
is an op with an effect; a program's required boundary set is computed from its term, and a platform card that
lacks one is a transfer-card refusal with the atom named. *Evidence:* writable today from documentation; witnessed
per platform as Phase I's shells land.

**E20. Discovery: the capability card is probed, not typed in.** *Today:* toolchains are probed (CM01); hardware
is not. *Needed:* a probe per environment that fills the capability card: `lscpu`, `sysctl` and `cpuid` for the
CPU; the pointer chase and the streaming copy for the hierarchy (E6); `vkGetPhysicalDeviceProperties` and
`VkPhysicalDeviceLimits`, `ID3D12Device::CheckFeatureSupport`, `MTLDevice` properties and GPU families, and
`cudaDeviceProp` for the device; then the op-card probe suite (E23). *Card math:* each probe is an observation card
with its provenance (`via`, as ANALYSE's facts carry), and a capability value is *measured* only when a probe
produced it, *declared* when a document did. Declared and measured values disagree on real machines: this host
declares a 260 MiB L3 and measures DRAM latency at 16 MiB (§4). *Evidence:* measurable today for the CPU side.

### 3.5 Device cards, transfer, scaling to new devices, and the Gödel layer

**E21. The environment card.** *Today:* the host block on a metric card (`machine`, `system`, `python`, `node`),
`resources.max_parallel` capped at `min(4, cores/2, RAM/4 GiB)` from a policy rather than a card. *Needed:* one
card per environment in D15's shape, holding or pointing to: the ISA card and its extension list, cores and SMT,
the memory-level cards (E6), the numeric-model card (E12, E13), the accelerator cards (E2, E7), the platform card
(E19), the API and driver cards (E16, E18), the limits (E5, E10), and the cost anchors measured there. The
generator's card is written by the probe (E20) and updated when the measurement date is older than the model's
policy; a runner's card is a declared card until a device run replaces its values. *Card math:* the card is the
hypothesis set H of D17 for every law applied for that environment, and the cost vector of D8 for every
optimization aimed at it. *Evidence:* writable today; the schema is the first deliverable of §6.

**E22. `cardmodel carry`: the transfer judgment as a command.** *Today:* `cardmodel analyse` runs every firing
on every *language* runner on the host. *Needed:* the same judgment with G and R explicit (D18): `cardmodel carry
FILE --to <environment card>` lists the gap, the firings inside the domain, the certificate laws whose hypotheses
fail on R, and the predicted cost with its tier; when R is in reach (Phase J4's device runners, or a software API
model), it runs the firings there and the verdict becomes *carried* or *refused* with the first differing input
named. *Card math:* the output is a transfer card keyed by the hashes of t, G's card and R's card, so a transfer
already judged is one lookup (SCALING §3.4), and a change to R's card (a driver update) invalidates exactly the
transfer cards that cite it. *Evidence:* buildable today over the CPU variants; device rows as devices arrive.

**E23. Scaling to a new device is adding cards, never engine code.** *Today:* adding a language is adding a
language card and templates, and the matrix grows a column ([ROADMAP.md](ROADMAP.md) §2). *Needed:* the same for a device: its
environment card (probed), then a **standard probe suite** that is *generated from the signature and the laws*:
one conformance cell per op card per numeric sort, one witness per divergence law at its boundary inputs, one
microbenchmark per cost anchor, the hierarchy chase, and the reduction-order test. The suite grows by itself when
an op card or a law is added, which is what makes device support self-developing in the sense of the project's
goal: the model knows what to measure on a machine it has never seen because the questions come from its own
signature. *Card math:* the suite is the set {(op, sort, inputs)} ∪ {(law, boundary inputs)} ∪ {(anchor, seed)},
a function of Σ and E alone; its results are the device's rows in every table of this document. *Evidence:*
runnable today on the CPU side (it is `cardmodel matrix`, `analyse` and `optimize --measure` pointed at one
environment card).

**E24. What transfers for free, and what must be re-derived: the Gödel view.** *Today:* content γ is a
homomorphism that forgets arrangement (D11); carry-over between signatures is fixed by the image of each atom and
has a gap (D13); every atom takes a prime forever (CM43). *Needed:* nothing new in the mathematics, and that is
the point. A kernel on a GPU and the same function as a loop on the CPU have one canonical term, hence one
content vector and one identity (D7): what the device changes is the *schedule* (a parallel composition versus a
sequential fold), the *layout* (E8) and the *cost*, all of which are arrangement that γ does not see. So the
identity of a function carries to every device unchanged, and the gcd of a kernel's content with a library's
content finds shared logic across devices (GODEL.md §2), while everything device-specific lives in the structure
code, the certificate and the cost. The device atoms themselves (instructions, API calls, capability names) take
primes in the ledger as any atom does, and a translation between two device signatures (Vulkan to Metal, PTX to
RDNA) is a carry-over whose gap is reported atom by atom. *Evidence:* proof-tier for the content statements
(GodelCore T1, T2); the atom primes are a ledger change made in the PR that adds the first device card.

## 4. Measured on this host while writing (2026-11-04)

Host: Linux x86-64, 4 vCPUs of a Xeon at 2.10 GHz under a hypervisor, 15 GiB, gcc 13.3, clang 18.1; `lscpu`
lists AVX, FMA and F16C; no GPU (`/dev/dri` absent, no Vulkan loader). The programs are twenty lines of C each
and are the first four probes of E23's suite; they will become cards when E21's schema exists.

| probe | result | what it says |
|---|---|---|
| pointer chase, random cycle, ns per dependent load | 16 KiB **1.9**, 64 KiB 3.1, 256 KiB 5.0, 1 MiB 7.6, 4 MiB **24.6**, 16 MiB **66.2**, 64 MiB 137.6 | the measured hierarchy: a 48 KiB L1 (the step at 64 KiB), a 2 MiB L2 (the step between 1 and 4 MiB), and DRAM from 16 MiB up. `lscpu` *declares* a 260 MiB L3; the program never sees it (E6, E20: declared ≠ measured) |
| `x = 1 + 2⁻²⁷`: `x·x − 1` versus `fma(x, x, −1)`, gcc -O2 -mfma | with gcc's default contraction both give 1.49011612493588075e−08; with `-ffp-contract=off` the two-rounding form gives 1.49011611938476562e−08 (= 2⁻²⁶) and the fused form 2⁻²⁶ + 2⁻⁵⁴ | the compiler contracted `MUL`;`ADD` into `MULADD` silently; the difference is one bit at the 2⁻⁵⁴ place (E12, `fp_contract`) |
| `5 × 10⁻³¹⁰ × 0.5`, -O2 versus -Ofast | 2.5 × 10⁻³¹⁰ versus **0**, and under -Ofast the input is no longer classified subnormal (DAZ) | FTZ and DAZ set process-wide by the fast-math start-up code: `denormal_flush` fires on the CPU today (E13) |
| sum of 4096 binary32 values (every third is 10⁸, the rest 1), -O2 versus -O3 -ffast-math | 136,599,666,688 versus 136,599,740,416 (exact: 136,600,002,730) | the vectorized form sums interleaved partial sums, so the answer depends on the runner's lane count; both are wrong, differently (E14, E1) |
| F16C conversions | 0.1 → 0.0999755859; 65,520 → ∞; 10⁻⁸ → 0 | binary16's rounding, overflow at 65,504 and underflow below 2⁻²⁴, exactly the `precision_loss` rows of E11 |

## 5. Measurable today, measurable with a device, or conjecture

| gap | on this host now | with a software API model (lavapipe, WARP) | with a device in reach (the user's Mac: ARM64, NEON, Apple GPU through Metal) | design only today |
|---|---|---|---|---|
| E1 SIMD lanes | witnessed (§4) | — | NEON rows | the lane sorts and lane-wise law cards |
| E2 SIMT | — | kernels run; obligations checked | subgroup size, divergence cost measured | the launch op and its obligations |
| E3 memory consistency | sampled with a seeded scheduler | — | ARM64 rows (weak ordering) | the `memory_order` law |
| E4 host side | obligations statically checkable once T_dev exists | fences, barriers, layouts witnessed | Metal's rows | T_dev's trace model |
| E5 watchdogs | `step_budget` as today | — | measured on macOS and iPadOS | per-device constants |
| E6 hierarchy | measured (§4) | — | Apple Silicon's levels | the cache model (bounded tier) |
| E7 host–device transfer | — | not meaningful on a CPU model | unified memory measured | the break-even and roofline theorems |
| E8 layout, alignment | witnessed for the CPU | `std140`, offset alignment witnessed | — | the layout function per sort |
| E9 address spaces | — | witnessed | — | waits for MATH_CORE's memory sort |
| E10 residency | — | — | measured | declared |
| E11 f16, bf16 | f16 conversion witnessed (§4); bf16 by exact `eval` | f16 arithmetic witnessed | — | the series with the fixed-width work |
| E12 contraction, ULP bounds | contraction witnessed (§4) | per-op ULP measured against M | Metal's fast-math defaults measured | the numeric-model card |
| E13 denormals | witnessed (§4) | the device's FTZ flags witnessed | — | the three laws |
| E14 reduction order | lane-count dependence witnessed (§4) | atomic order sampled | — | the reduction op cards |
| E15 integers on a GPU | — | wrap, shift and conversion rows witnessed | — | rows per shading language |
| E16 APIs as one theory | the theory and API cards writable | cells run | Metal cells run | T_dev |
| E17 shading languages | templates writable; no validator or loader here | conformance cells run | — | SPIR-V and WGSL cards |
| E18 driver fingerprints | the card shape | the software model's version is a fingerprint | real driver rows | — |
| E19 OS surfaces | Linux and macOS cards from documentation | — | macOS and iPadOS witnessed (Phase I) | Windows, Android |
| E20 discovery probes | CPU side runs today | API queries run | Metal queries run | — |
| E21 environment card | the generator's card measurable now | — | the Mac's card measured | the schema |
| E22 `carry` | over the CPU variants | with software rows | with device rows | the command |
| E23 probe suite | the CPU half exists as `matrix`, `analyse`, `optimize --measure` | the GPU half runs | the device half runs | generation from Σ and E |
| E24 Gödel layer | proof-tier (GodelCore T1, T2) | — | — | the device atoms' primes |

## 6. Order of work

Each step lands as cards, a test that pins them to M, and a row in the tables above; nothing is claimed above its
tier. Steps marked † depend on the fixed-width type series (MATH_CORE F3, the foundations workstream).

1. **V-A. The environment card and the probes (E20, E21, E6).** The card schema, the CPU probe (`lscpu` or
   `sysctl`, the chase, the streaming copy) and the full fingerprint on every metric and witness card. The
   generator's own card is written on the first run; `resources.max_parallel` reads it. Measurable now.
2. **V-B. Numeric-model cards and the three CPU-witnessed laws (E12, E13, E14).** `fp_contract`,
   `denormal_flush` and `reduction_order` as laws in ANALYSE's family, with rows for the existing runner variants,
   witnessed by §4's probes made into cards. The e-graph reads the float laws it may fire from the target's
   numeric-model card (D17).
3. **V-C.† f16 and bf16 in the type series (E11), lane sorts (E1).** The series extended, `precision_loss`,
   V(n, s) with its lane-wise law cards, SSE/AVX/NEON instruction cards following `isa/armv5te`'s pattern.
4. **V-D. The device theory and SPIR-V (E16, E17, E4).** T_dev's op cards, the Vulkan and Metal API cards with
   their carry-over map and gap, a SPIR-V language card, and lavapipe as a probed runner in CI, so the GPU
   conformance cells are witnessed without hardware.
5. **V-E.† Kernels (E2, E9, E15, E8).** The launch op with its independence and uniformity obligations, address
   spaces over MATH_CORE's memory sort, BV(32) kernels, layouts and alignment rows.
6. **V-F. `cardmodel carry` and the transfer card (E22, E23, E5, E10).** The judgment over every environment card
   in reach, the generated probe suite, and the first real device rows: the user's Mac through Phase J4's device
   runners, then iPadOS with Phase I.
7. **V-G. Memory consistency and drivers (E3, E18, E19).** The `memory_order` law with the seeded scheduler,
   driver-flaw cards, and platform cards for Windows and Android.

## 7. Honest limits

* A device's silicon, firmware and driver are outside the cards. They are reached by running and measuring, never
  derived (SCALING §7), so every device row is witnessed or declared, and a declared row is a claim about a document.
* A hardware-only GPU with no public ISA (Apple's) is modelled at the API level only; its instruction cards do not
  exist, and its numeric model is what the probe suite measures through Metal.
* Timing is a distribution. Clocks, thermals, neighbours on a shared host and schedulers move it, so cost anchors
  stay medians with MAD and a date, as metric cards are today, and a predicted cost is ranked, not promised.
* A software API model agrees with the hardware where it was sampled to agree. Its witness is honest about which
  model produced it; it is never presented as the device's.
* Program equivalence and race freedom are undecidable. A kernel's independence obligation is proved when interval
  analysis decides it and sampled otherwise, and "sampled" is the word used.
* This document enumerates what the model lacks; it does not land any of it. The commit that lands a step moves its
  row of §5 and records the measurement it was made with.
