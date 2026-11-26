"""단계별 소요 시간 측정.  .venv\\Scripts\\python scripts\\bench.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

t0 = time.perf_counter()
import pandas  # noqa: E402,F401
import pulp  # noqa: E402
import statsmodels  # noqa: E402,F401

from lng import optimizer as opt  # noqa: E402
from lng.planner import Scenario, build_inputs  # noqa: E402

print(f"import            {time.perf_counter() - t0:6.2f}s")
print("pulp", pulp.__version__, "| solvers:", pulp.listSolvers(onlyAvailable=True), "| using:", opt.solver_name(), flush=True)

for sc in [Scenario(), Scenario(name="hormuz_6m", hormuz_blocked_months=6, spot_price_multiplier=1.5, spot_volume_multiplier=0.6)]:
    print(f"{sc.name:<12} building...", flush=True)
    t = time.perf_counter()
    inp, _ = build_inputs(sc)
    t_build = time.perf_counter() - t
    print(f"{sc.name:<12} build {t_build:5.2f}s, solving...", flush=True)
    t = time.perf_counter()
    res = opt.solve(inp)
    t_solve = time.perf_counter() - t
    print(f"{sc.name:<12} build {t_build:5.2f}s | solve {t_solve:5.2f}s "
          f"(solver {res.get('solve_seconds')}s, time limit hit={res.get('time_limited')}) | {res['status']}")
