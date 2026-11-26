"""LNG 공급망 배분 에이전트 실행 진입점.

  python main.py demo                 기본 vs 호르무즈 시나리오 비교
  python main.py chat                 Solar 채팅 (UPSTAGE_API_KEY 필요)
  python main.py chat --offline       키 없이 키워드 라우터로 도구 호출 체험
  python main.py approve <order_id>   담당자 승인 (사람만)
  python main.py ingest <PDF 또는 폴더>  Studio 에이전트로 문서 처리 -> data/studio_output
  python main.py studio-check         키로 보이는 Studio 에이전트 목록 확인
  python main.py history [키워드]      프로젝트별 보고서마다 가동 예정일이 어떻게 바뀌었는지
  python main.py renormalize          data/studio_raw 원본으로 data/studio_output 다시 만들기 (API 호출 없음)
  python main.py eval-studio [--reuse] [--cases A,D]  데이터셋 7건을 Studio로 돌려 정답지와 비교

  전체 흐름 (워크플로우 A -> B -> 최적화 -> C -> 승인)
  python main.py make-a-cases         프로젝트별 최신 보고서 2건 합본 만들기 (data/a_cases)
  python main.py ingest-a [--workers 3] [--force]  A로 공급 파라미터 추출 (data/studio_params)
  python main.py review               A, B가 검토 필요로 넘긴 건 보기
  python main.py approve-param <key> --approver 이름 [--set 키=값 ...] [--reject] [--note 메모]
  python main.py ingest-b <수급계획 PDF>  B로 수요 전망과 기지 용량 추출 (data/plan_params)
  python main.py run-cycle [--hormuz 3 ...]  최적화 -> 실행안 PDF -> C 검증 -> 승인 요청 또는 재계획
  python main.py check-plan <실행안 PDF>  사람이 고친 실행안 검증, 재계획 필요면 다시 계획
  python main.py api [--port 8000]    Flutter 앱용 백엔드 (http://localhost:8000/docs)
  LNG_STUDIO_FAKE=1 이면 Studio 대신 정답지와 코드 검산으로 돌린다 (오프라인 데모)
"""
import argparse
import json

try:  # .env에서 UPSTAGE_API_KEY 등 읽기
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from lng import planner, tools


def demo():
    scenarios = [
        planner.Scenario(),
        planner.Scenario(name="hormuz_6m", hormuz_blocked_months=6, spot_price_multiplier=1.5, spot_volume_multiplier=0.6),
        planner.Scenario(name="hormuz_6m_us_delay", hormuz_blocked_months=6, spot_price_multiplier=1.5,
                         spot_volume_multiplier=0.6, us_extra_delay_months=6),
        planner.Scenario(name="hormuz_6m_tight_spot", hormuz_blocked_months=6, spot_price_multiplier=1.8,
                         spot_volume_multiplier=0.25),
    ]
    print(f"{'scenario':<24}{'cost(M$)':>12}{'spot':>7}{'US_unc':>8}{'short(kt)':>11}  note")
    for sc in scenarios:
        s = planner.summarize(planner.run(sc))
        print(f"{s['scenario']:<24}{s['total_cost_musd']:>12,.0f}{s['spot_cargoes']:>7}{s['us_uncontracted_cargoes']:>8}{s['total_shortage_kt']:>11,.1f}  {'시간제한 해' if s['time_limited'] else ''}")
    print("\n* 모든 입력은 샘플 데이터입니다 (data/sample, data/studio_output).")


def chat(offline: bool):
    if offline:
        from lng.orchestrator import offline_route
        print("[오프라인 모드] 키워드로 도구를 고릅니다. 종료: exit")
        while (q := input("\n> ").strip()) not in ("exit", "quit"):
            name, args = offline_route(q)
            print(f"  -> {name}({args})")
            print(json.dumps(tools.REGISTRY[name](**args), ensure_ascii=False, indent=1, default=str)[:3000])
        return
    from lng.orchestrator import Orchestrator
    bot = Orchestrator()
    print("Solar 오케스트레이터. 종료: exit")
    while (q := input("\n> ").strip()) not in ("exit", "quit"):
        print(bot.ask(q, on_tool=lambda n, a: print(f"  [tool] {n}({a})")))


def ingest(target: str, force: bool = False, workers: int = 3):
    """PDF를 Studio 에이전트로 처리. 이미 성공한 파일과 내용이 똑같은 중복 파일은 API를 다시 부르지 않는다."""
    import hashlib
    import shutil
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path

    from lng.studio_client import DEFAULT_DIR, RAW_DIR, run_studio_agent

    p = Path(target)
    files = sorted(p.rglob("*.pdf")) if p.is_dir() else [p]  # 하위 폴더까지
    if not files:
        print("PDF가 없습니다:", target)
        return

    def key(f):  # 사업자 폴더 이름까지 붙여서 파일명이 겹쳐도 덮어쓰지 않게
        return f"{f.parent.name}__{f.stem}" if p.is_dir() else f.stem

    def ok_raw(f):
        for k in (key(f), f.stem):  # f.stem은 예전 방식으로 저장된 결과
            r = RAW_DIR / f"{k}.json"
            if r.exists() and '"status": "completed"' in r.read_text(encoding="utf-8"):
                return True
        return False

    # 같은 내용의 PDF가 여러 사업자 폴더에 중복으로 있는 경우가 있어서 내용 해시로 한 번만 처리
    groups: dict[str, list[Path]] = {}
    for f in files:
        groups.setdefault(hashlib.sha1(f.read_bytes()).hexdigest(), []).append(f)

    todo, copies, skipped = [], [], 0
    for h, fs in groups.items():
        done = next((f for f in fs if ok_raw(f)), None)
        if done and not force:
            skipped += 1
            copies += [(done, f) for f in fs if f is not done and not ok_raw(f)]
        else:
            todo.append(fs[0])
            copies += [(fs[0], f) for f in fs[1:]]
    pages_note = f", 중복 {len(files) - len(groups)}건은 한 번만 처리" if len(files) > len(groups) else ""
    print(f"PDF {len(files)}건: 이미 처리 {skipped}건 건너뜀, 새로 처리 {len(todo)}건{pages_note}", flush=True)

    def one(f):
        rec = run_studio_agent(str(f), key=key(f))
        keys = [k for k in ("project", "report_date", "stage", "first_lng_date", "expected_operational_date") if rec.get(k)]
        return ", ".join(f"{k}={rec[k]}" for k in keys) or "추출된 필드 없음 (data/studio_raw 확인)"

    ok, fails = 0, []
    with ThreadPoolExecutor(max(1, workers)) as ex:
        futs = {ex.submit(one, f): f for f in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            f = futs[fut]
            try:
                print(f"[{i}/{len(todo)}] {f.parent.name}/{f.name}\n    {fut.result()}", flush=True)
                ok += 1
            except Exception as e:
                fails.append(f)
                print(f"[{i}/{len(todo)}] {f.parent.name}/{f.name}\n    실패: {e}", flush=True)

    for src, dst in copies:  # 중복 파일은 결과만 복사 (API 호출 없음)
        for d in (RAW_DIR, DEFAULT_DIR):
            s_file = next((d / f"{k}.json" for k in (key(src), src.stem) if (d / f"{k}.json").exists()), None)
            if s_file and s_file.name != f"{key(dst)}.json":
                shutil.copyfile(s_file, d / f"{key(dst)}.json")
    print(f"\n{ok}/{len(todo)}건 완료, 실패 {len(fails)}건. 실패한 건은 다시 실행하면 그것만 처리합니다.")


def ingest_a_all(workers: int = 3, force: bool = False, only: str = ""):
    import csv
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from lng import workflows

    root = Path(__file__).resolve().parent
    man = root / "data" / "a_cases" / "manifest.csv"
    if not man.exists():
        print("data/a_cases가 없습니다. 먼저 python main.py make-a-cases")
        return
    rows = list(csv.DictReader(open(man, encoding="utf-8-sig")))
    if only:
        keys = {k.strip() for k in only.split(",") if k.strip()}
        todo = [r for r in rows if r["case_key"] in keys]
    else:
        todo = [r for r in rows if force or not (workflows.PARAMS_DIR / f"{r['case_key']}.json").exists()]
    print(f"A 케이스 {len(rows)}건 중 {len(todo)}건 처리 (이미 한 건은 --force로 다시)")

    def one(r):
        try:
            rec = workflows.ingest_a(root / "data" / "a_cases" / r["file"], r["case_key"])
            return f"  {r['case_key'][:40]:40s} {rec.get('stage') or '-':13s} {rec.get('online_month') or '-':8s} {rec.get('config_status')}"
        except Exception as e:  # noqa: BLE001
            return f"  {r['case_key'][:40]:40s} 실패: {e}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for line in ex.map(one, todo):
            print(line)
    pend = workflows.pending_reviews()
    print(f"\n검토 필요 {len(pend)}건. python main.py review 로 확인하세요." if pend else "\n검토 필요 없음.")


def review():
    from lng import workflows

    pend = workflows.pending_reviews()
    if not pend:
        print("검토 필요로 남은 건이 없습니다.")
    for r in pend:
        print(f"\n[{r['case_key']}] {r.get('docket')}  단계 {r.get('stage')}  가동 {r.get('online_month') or '-'}"
              f"  한국 구매자 {r.get('kr_buyers') or '-'}")
        print(f"  이유: {r.get('reason')}")
        print(f"  반영: python main.py approve-param {r['case_key']} --approver 이름   제외: ... --reject")


def history(keyword: str = ""):
    from collections import defaultdict

    from lng import supply
    from lng.studio_client import load_extractions

    recs = [r for r in load_extractions() if r.get("doc_type") == "semi_annual_report"
            and keyword.lower() in (r.get("project") or "").lower()]
    by = defaultdict(list)
    for r in recs:
        by[r.get("source_folder") or supply._docket_key(r.get("docket")) or r.get("project")].append(r)
    for key, rs in sorted(by.items()):
        rs.sort(key=lambda r: r.get("report_date") or "")
        print(f"\n[{rs[-1].get('project')}] {key}  (보고서 {len(rs)}건)")
        for r in rs:
            mark = " (추정)" if r.get("expected_operational_date_inferred") else ""
            extra = f"  단계 {r.get('stage') or '-'}" + (f"  첫LNG {r['first_lng_date']}" if r.get("first_lng_date") else "")
            kr = [c["buyer"] for c in r.get("long_term_contracts", []) if supply.is_korean_buyer(c)]
            print(f"  {r.get('report_date')}  가동예정 {r.get('expected_operational_date') or '-'}{mark}"
                  f"  허가 {r.get('authorized_mtpa') or '-'} MTPA  미계약 {r.get('uncontracted_mtpa') if r.get('uncontracted_mtpa') is not None else '-'}"
                  f"  계약 {len(r.get('long_term_contracts', []))}건{'  한국: ' + ', '.join(kr) if kr else ''}{extra}")
    prof = supply.project_profiles(recs)
    if len(prof):
        print("\n지연 요약")
        print(prof[["docket", "reports", "stage", "base_operating", "first_lng_date", "latest_expected", "date_source", "operating",
                    "slip_count", "tau_months", "contracts", "contracted_mtpa", "uncontracted_mtpa"]].to_string(index=False))
    elif not recs:
        print("해당하는 반기 보고서 추출 결과가 없습니다.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    c = sub.add_parser("chat")
    c.add_argument("--offline", action="store_true")
    ap_ = sub.add_parser("approve")
    ap_.add_argument("order_id")
    ap_.add_argument("--approver", default="담당자")
    sub.add_parser("studio-check")
    sub.add_parser("renormalize")
    ing = sub.add_parser("ingest")
    ing.add_argument("target")
    ing.add_argument("--force", action="store_true")
    ing.add_argument("--workers", type=int, default=3, help="동시에 처리할 파일 수")
    ev = sub.add_parser("eval-studio")
    ev.add_argument("--reuse", action="store_true")
    ev.add_argument("--cases", default="")
    ev.add_argument("--workers", default="3")
    apis = sub.add_parser("api")
    apis.add_argument("--port", type=int, default=8000)
    sub.add_parser("make-a-cases")
    ia = sub.add_parser("ingest-a")
    ia.add_argument("--workers", type=int, default=3)
    ia.add_argument("--force", action="store_true")
    ia.add_argument("--only", default="", help="쉼표로 구분한 케이스 키만 다시 처리 (예: Venture_Global_CP2_LNG_LLC)")
    sub.add_parser("review")
    apr = sub.add_parser("approve-param")
    apr.add_argument("key")
    apr.add_argument("--approver", default="담당자")
    apr.add_argument("--note", default="")
    apr.add_argument("--reject", action="store_true")
    apr.add_argument("--set", action="append", default=[], metavar="키=값",
                     help="원문을 보고 고친 값으로 반영 (예: --set stage=operating --set online_month=2019-12). kr_buyers는 ;로 구분")
    ib = sub.add_parser("ingest-b")
    ib.add_argument("pdf")
    rc = sub.add_parser("run-cycle")
    rc.add_argument("--name", default="")
    rc.add_argument("--hormuz", type=int, default=0)
    rc.add_argument("--spot-volume", type=float, default=1.0)
    rc.add_argument("--spot-price", type=float, default=1.0)
    rc.add_argument("--us-delay", type=int, default=0)
    rc.add_argument("--demand", type=float, default=1.0)
    cp = sub.add_parser("check-plan")
    cp.add_argument("pdf")
    hi = sub.add_parser("history")
    hi.add_argument("keyword", nargs="?", default="")
    args = ap.parse_args()
    if args.cmd == "demo":
        demo()
    elif args.cmd == "chat":
        chat(args.offline)
    elif args.cmd == "ingest":
        ingest(args.target, args.force, args.workers)
    elif args.cmd == "history":
        history(args.keyword)
    elif args.cmd == "eval-studio":
        import subprocess
        import sys

        cmd = [sys.executable, "scripts/eval_studio.py", "--workers", args.workers]
        if args.reuse:
            cmd.append("--reuse")
        if args.cases:
            cmd += ["--cases", args.cases]
        subprocess.run(cmd, check=False)
    elif args.cmd == "api":
        import uvicorn

        uvicorn.run("api.server:app", host="0.0.0.0", port=args.port)
    elif args.cmd == "make-a-cases":
        import subprocess
        import sys

        subprocess.run([sys.executable, "scripts/make_a_cases.py"], check=False)
    elif args.cmd == "ingest-a":
        ingest_a_all(args.workers, args.force, args.only)
    elif args.cmd == "review":
        review()
    elif args.cmd == "approve-param":
        from lng import workflows

        if args.reject:
            r = workflows.reject_param(args.key, args.approver, args.note)
        else:
            sets = dict(x.split("=", 1) for x in args.set)
            r = workflows.approve_param(args.key, args.approver, args.note, sets)
        print(f"{args.key}: {r['review']['status']} ({args.approver})")
        for k, v in (r["review"].get("overrides") or {}).items():
            print(f"  {k}: {v['studio']!r} -> {v['reviewer']!r}")
    elif args.cmd == "ingest-b":
        from lng import workflows

        r = workflows.ingest_b(args.pdf)
        print(json.dumps({k: r.get(k) for k in workflows.KEYS["B"]}, ensure_ascii=False, indent=1))
        if r["review"]["status"] != "auto":
            print("검토 필요로 나와서 최적화에는 아직 쓰지 않습니다. 내용을 확인하세요.")
    elif args.cmd == "run-cycle":
        from lng import cycle, planner

        sc = planner.Scenario(name=args.name or ("hormuz" + str(args.hormuz) if args.hormuz else "baseline"),
                              hormuz_blocked_months=args.hormuz, spot_volume_multiplier=args.spot_volume,
                              spot_price_multiplier=args.spot_price, us_extra_delay_months=args.us_delay,
                              demand_multiplier=args.demand)
        out = cycle.run_cycle(sc)
        o = out["order"]
        print(f"\n결과: {out['status']}  주문 초안 {o['order_id']} (orders/{o['order_id']}.json)")
        print(f"입력: {o.get('inputs_used')}")
        print(f"Studio 판단: {o['studio_check'].get('reason')}")
        if out["status"] == "PENDING_APPROVAL":
            print(f"승인: python main.py approve {o['order_id']} --approver 이름")
    elif args.cmd == "check-plan":
        from lng import cycle

        out = cycle.check_plan(args.pdf)
        if out.get("replan"):
            o = out["replan"]["order"]
            print(f"\n재계획 결과: {out['replan']['status']}  주문 초안 {o['order_id']}")
    elif args.cmd == "renormalize":
        from lng.studio_client import renormalize_all

        print(f"{renormalize_all()}건 다시 변환했습니다 (data/studio_output).")
    elif args.cmd == "studio-check":
        from lng.studio_client import check_setup

        r = check_setup()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if r.get("agent_found"):
            print("\n.env의 에이전트가 이 키의 조직에 있습니다. 조직은 맞으니 요금제/사용량 쪽 문제입니다.")
        elif "visible_agents" in r:
            print("\n.env의 에이전트 ID가 이 키로 보이는 목록에 없습니다. 키와 에이전트가 다른 조직일 가능성이 큽니다.")
    else:
        print(json.dumps(tools.approve_order(args.order_id, args.approver), ensure_ascii=False, indent=1))
