import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// 계획 세우기: 상황을 질문으로 고르면 최적화 -> 실행안 -> Studio C 검사 -> 승인 요청까지 한 번에.
class PlanPage extends StatefulWidget {
  const PlanPage({super.key, required this.onGo});
  final void Function(int) onGo;
  @override
  State<PlanPage> createState() => _PlanPageState();
}

class _PlanPageState extends State<PlanPage> {
  int _hormuz = 3;
  double _spot = 1.0;
  int _usDelay = 0;
  double _demand = 1.0;
  Map<String, dynamic>? _job;
  Map<String, dynamic>? _compare;
  bool _busy = false;

  Map<String, dynamic> get _req => {'hormuz': _hormuz, 'spot_volume': _spot, 'us_delay': _usDelay, 'demand': _demand};

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _job = null;
    });
    try {
      final j = Map<String, dynamic>.from(await Api.instance.post('/cycle', _req));
      final done = await Api.instance.waitJob(j['id'], onUpdate: (u) {
        if (mounted) setState(() => _job = u);
      });
      setState(() => _job = done);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _quick() async {
    setState(() => _busy = true);
    try {
      final r = await Api.instance.post('/scenario', {..._req, 'name': 'what_if'});
      setState(() => _compare = Map<String, dynamic>.from(r));
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_job != null && _job!['status'] == 'running') {
      return PageScaffold(title: '계획을 세우고 있어요', children: [
        Working(_job),
        Box(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(children: const [
            RowItem(icon: Icons.hub_rounded, title: '배분 최적화', subtitle: '공급원, 기지, 월별로 카고를 나눠요'),
            RowItem(icon: Icons.picture_as_pdf_rounded, title: '실행안 만들기', subtitle: '앞 3개월분을 승인용 문서로 만들어요'),
            RowItem(icon: Icons.rule_rounded, iconColor: C.orange, title: '검증 시스템', subtitle: '용량, 안전재고, 계약, 합계를 확인해요'),
          ]),
        ),
      ]);
    }
    if (_job != null) return _result();

    return PageScaffold(
      title: '어떤 상황을 대비할까요?',
      subtitle: '고른 상황으로 5년 조달을 최적화하고, 앞 3개월 실행안을 검증 시스템이 검사해요.',
      bottom: Row(children: [
        Expanded(child: SecondaryButton('비용만 먼저 볼게요', onPressed: _busy ? null : _quick)),
        const SizedBox(width: 12),
        Expanded(flex: 2, child: PrimaryButton('계획 세우기', busy: _busy, onPressed: _run)),
      ]),
      children: [
        Box(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Question('호르무즈 해협이 막힌다면?',
                Choices<int>(options: const [(0, '안 막혀요'), (1, '1개월'), (3, '3개월'), (6, '6개월')], value: _hormuz,
                    onChanged: (v) => setState(() => _hormuz = v)),
                hint: '카타르 물량이 그동안 들어오지 못해요'),
            Question('현물은 얼마나 살 수 있을까요?',
                Choices<double>(options: const [(1.0, '평소만큼'), (0.6, '60%'), (0.3, '30%')], value: _spot,
                    onChanged: (v) => setState(() => _spot = v)),
                hint: '여러 나라가 동시에 사면 구하기 어려워져요'),
            Question('미국 프로젝트가 더 늦어진다면?',
                Choices<int>(options: const [(0, '예정대로'), (6, '6개월'), (12, '12개월')], value: _usDelay,
                    onChanged: (v) => setState(() => _usDelay = v))),
            Question('수요는 어떨까요?',
                Choices<double>(options: const [(0.9, '10% 적게'), (1.0, '전망대로'), (1.1, '10% 많이')], value: _demand,
                    onChanged: (v) => setState(() => _demand = v))),
          ]),
        ),
        if (_compare != null) _compareBox(),
      ],
    );
  }

  Widget _compareBox() {
    final vs = Map<String, dynamic>.from(_compare!['vs_baseline'] ?? {});
    final dc = (vs['cost_change_musd'] as num?) ?? 0;
    return Box(
      title: '평소보다 ${dc >= 0 ? '${num0(dc)}백만 달러 더' : '${num0(-dc)}백만 달러 덜'} 들어요',
      child: StatRow([
        BigStat('1년 총비용', num0(_compare!['total_cost_musd']), unit: 'M\$'),
        BigStat('현물 카고', '${_compare!['spot_cargoes']}', unit: '척'),
        BigStat('부족', num0(_compare!['total_shortage_kt']), unit: 'kt',
            color: ((_compare!['total_shortage_kt'] as num?) ?? 0) > 0 ? C.red : null),
      ]),
    );
  }

  Widget _result() {
    if (_job!['status'] == 'error') {
      return PageScaffold(
          title: '계획을 세우지 못했어요',
          subtitle: _job!['error']?.toString(),
          bottom: PrimaryButton('다시 하기', onPressed: () => setState(() => _job = null)),
          children: const []);
    }
    final r = Map<String, dynamic>.from(_job!['result'] ?? {});
    final order = Map<String, dynamic>.from(r['order'] ?? {});
    final check = Map<String, dynamic>.from(order['studio_check'] ?? {});
    final history = [for (final h in (r['history'] as List? ?? [])) Map<String, dynamic>.from(h)];
    final purchases = [for (final p in (r['purchase_requests'] as List? ?? [])) Map<String, dynamic>.from(p)];
    final spot = purchases.where((p) => p['source'] == 'SPOT').fold<num>(0, (a, p) => a + ((p['cargoes'] as num?) ?? 0));
    final usUnc = purchases.where((p) => p['source'] == 'US_UNCONTRACTED').fold<num>(0, (a, p) => a + ((p['cargoes'] as num?) ?? 0));
    final shortage = List<String>.from(check['shortage_rows'] ?? const []);
    final status = r['status']?.toString();
    final (ok, title) = switch (status) {
      'PENDING_APPROVAL' => (true, '승인을 요청할 준비가 됐어요'),
      'NEEDS_REVIEW' => (false, '검증 시스템과 교차 검산이 달라\n사람 확인이 필요해요'),
      _ => (false, '다시 계획해도 문제가 남아\n담당자에게 넘겼어요'),
    };

    return PageScaffold(
      title: '',
      bottom: Row(children: [
        Expanded(child: SecondaryButton('조건 바꿔보기', onPressed: () => setState(() => _job = null))),
        const SizedBox(width: 12),
        Expanded(flex: 2, child: PrimaryButton(ok ? '승인하러 가기' : '확인하러 가기', onPressed: () => widget.onGo(2))),
      ]),
      children: [
        ResultHead(ok: ok, title: title, body: check['reason']?.toString()),
        Box(
          child: StatRow([
            BigStat('3개월 계획 물량', num0(check['total_planned_kt']), unit: 'kt'),
            BigStat('현물 구매', num0(spot), unit: '척'),
            BigStat('미국 미계약 구매', num0(usUnc), unit: '척'),
          ]),
        ),
        Box(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(children: [
            RowItem(
              icon: shortage.isEmpty ? Icons.check_circle_rounded : Icons.warning_rounded,
              iconColor: shortage.isEmpty ? C.green : C.red,
              title: shortage.isEmpty ? '부족한 달이 없어요' : '현물로도 못 채우는 달이 있어요',
              subtitle: shortage.isEmpty ? null : shortage.join('  ·  '),
            ),
            for (final h in history)
              RowItem(
                icon: Icons.picture_as_pdf_rounded,
                iconColor: (h['studio_decision'] == '승인 요청') ? C.green : C.orange,
                title: '${h['attempt']}번째 실행안 · ${label(h['studio_decision']?.toString())}',
                subtitle: '검증 시스템 ${label(h['studio_decision']?.toString())} / 교차 검산 ${label(h['code_decision']?.toString())}',
                onTap: () => openUrl(Api.instance.fileUrl(h['pdf'].toString())),
              ),
          ]),
        ),
        Box(
          child: Details(
            title: '이번 계획에 쓴 입력 보기',
            child: RawFields(Map<String, dynamic>.from(order['inputs_used'] ?? {})),
          ),
        ),
      ],
    );
  }
}
