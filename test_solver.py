"""Quick sanity test for the CP-SAT model (without Streamlit)."""
import calendar
from ortools.sat.python import cp_model

SHIFT_REST, SHIFT_DAY, SHIFT_NIGHT, SHIFT_AKE = 0, 1, 2, 3
SHIFTS = [SHIFT_REST, SHIFT_DAY, SHIFT_NIGHT, SHIFT_AKE]
LABEL = {0: "休", 1: "日", 2: "夜", 3: "明"}

# 設定
N = 8  # nurses
year, month = 2026, 5
_, D = calendar.monthrange(year, month)
min_day, min_night = 3, 1
max_consecutive = 5
max_nights, min_nights = 8, 2
min_off = 9

# ダミー看護師データ: 0,1はリーダー; 7番目は日勤のみ
roles = ["リーダー", "リーダー"] + ["一般"] * 5 + ["日勤のみ"]
can_night = [True] * 7 + [False]
off_requests = {0: [5, 15], 3: [10, 20], 6: [1, 2, 3]}

model = cp_model.CpModel()
x = {(n, d, s): model.NewBoolVar(f"x_{n}_{d}_{s}")
     for n in range(N) for d in range(D) for s in SHIFTS}

for n in range(N):
    for d in range(D):
        model.AddExactlyOne([x[n, d, s] for s in SHIFTS])

for d in range(D):
    model.Add(sum(x[n, d, SHIFT_DAY] for n in range(N)) >= min_day)
    model.Add(sum(x[n, d, SHIFT_NIGHT] for n in range(N)) >= min_night)

for n in range(N):
    for d in range(D - 1):
        model.Add(x[n, d + 1, SHIFT_AKE] >= x[n, d, SHIFT_NIGHT])

for n in range(N):
    model.Add(x[n, 0, SHIFT_AKE] == 0)
    for d in range(1, D):
        model.Add(x[n, d, SHIFT_AKE] <= x[n, d - 1, SHIFT_NIGHT])

# 夜勤 → 明け → 休 パターン
for n in range(N):
    for d in range(D - 1):
        model.Add(x[n, d + 1, SHIFT_REST] >= x[n, d, SHIFT_AKE])

for n in range(N):
    if roles[n] == "日勤のみ" or not can_night[n]:
        for d in range(D):
            model.Add(x[n, d, SHIFT_NIGHT] == 0)

leader_idx = [i for i, r in enumerate(roles) if r == "リーダー"]
# リーダー夜勤はソフト制約としてペナルティ化

for n, days in off_requests.items():
    for day in days:
        model.Add(x[n, day - 1, SHIFT_REST] == 1)

for n in range(N):
    nights_n = sum(x[n, d, SHIFT_NIGHT] for d in range(D))
    model.Add(nights_n <= max_nights)
    if roles[n] != "日勤のみ" and can_night[n]:
        model.Add(nights_n >= min_nights)

for n in range(N):
    off_n = sum(x[n, d, SHIFT_REST] + x[n, d, SHIFT_AKE] for d in range(D))
    model.Add(off_n >= min_off)

for n in range(N):
    for d in range(D - max_consecutive):
        window = [x[n, d + k, SHIFT_REST] + x[n, d + k, SHIFT_AKE]
                 for k in range(max_consecutive + 1)]
        model.Add(sum(window) >= 1)

workdays = [sum(x[n, d, SHIFT_DAY] + x[n, d, SHIFT_NIGHT] for d in range(D)) for n in range(N)]
nights = [sum(x[n, d, SHIFT_NIGHT] for d in range(D)) for n in range(N)]
max_wd = model.NewIntVar(0, D, "max_wd")
min_wd = model.NewIntVar(0, D, "min_wd")
max_ng = model.NewIntVar(0, D, "max_ng")
min_ng = model.NewIntVar(0, D, "min_ng")
model.AddMaxEquality(max_wd, workdays)
model.AddMinEquality(min_wd, workdays)
model.AddMaxEquality(max_ng, nights)
model.AddMinEquality(min_ng, nights)
leader_absent_penalty = 0
if leader_idx:
    leader_absent = []
    for d in range(D):
        lc = sum(x[n, d, SHIFT_NIGHT] for n in leader_idx)
        a = model.NewBoolVar(f"leader_absent_{d}")
        model.Add(lc == 0).OnlyEnforceIf(a)
        model.Add(lc >= 1).OnlyEnforceIf(a.Not())
        leader_absent.append(a)
    leader_absent_penalty = sum(leader_absent)

model.Minimize((max_wd - min_wd) * 3 + (max_ng - min_ng) * 2 + leader_absent_penalty)

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 15.0
# Python 3.14 + ortools 9.15 では並列ソルバがハングするため単一ワーカーに固定
solver.parameters.num_search_workers = 1
status = solver.Solve(model)

print(f"Status: {solver.StatusName(status)}")
print(f"Days in {year}-{month:02d}: {D}")
if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    print(f"Objective: {solver.ObjectiveValue()}")
    print()
    # header
    print("Name".ljust(8) + "|" + "".join(str((d+1) % 10) for d in range(D)))
    print("-" * (8 + 1 + D))
    for n in range(N):
        line = f"N{n}({roles[n][:2]})".ljust(8) + "|"
        for d in range(D):
            for s in SHIFTS:
                if solver.Value(x[n, d, s]) == 1:
                    line += LABEL[s]
                    break
        print(line)
    print()
    # summary
    print("Name    | 日  夜  明  休  勤務")
    for n in range(N):
        day_c = sum(solver.Value(x[n, d, SHIFT_DAY]) for d in range(D))
        ng_c = sum(solver.Value(x[n, d, SHIFT_NIGHT]) for d in range(D))
        ake_c = sum(solver.Value(x[n, d, SHIFT_AKE]) for d in range(D))
        rest_c = sum(solver.Value(x[n, d, SHIFT_REST]) for d in range(D))
        print(f"N{n}".ljust(8) + f"| {day_c:2}  {ng_c:2}  {ake_c:2}  {rest_c:2}  {day_c+ng_c:2}")
else:
    print("INFEASIBLE or timeout")
