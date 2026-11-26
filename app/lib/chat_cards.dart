import 'package:flutter/material.dart';

import 'actions.dart';
import 'api.dart';
import 'pages/approve_page.dart';
import 'plan_detail.dart';
import 'procurement.dart';
import 'theme.dart';
import 'widgets.dart';

/// 에이전트가 부른 도구의 결과 카드. 서버가 tool_end 이벤트의 card로 보낸다.
/// 숫자와 표는 카드가 보여주고, 에이전트 답은 핵심만 말한다.
class ChatCard extends StatelessWidget {
  const ChatCard(this.card, {super.key, this.onChanged});
  final Map<String, dynamic> card;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    // 승인, 반영이 나중에 일어나도 카드가 최신 상태를 보이도록 Live가 바뀌면 다시 그린다
    return ListenableBuilder(
      listenable: Listenable.merge([Live.orders, Live.pendingReviews]),
      builder: (context, _) => _frame(_body()),
    );
  }

  Widget _body() {
    return switch (card['type']) {
      'overview' => _OverviewCard(card),
      'doc' => _DocCard(card, onChanged: onChanged),
      'reviews' => _ReviewsCard(card, onChanged: onChanged),
      'supply' => _SupplyCard(card),
      'scenario' => _ScenarioCard(card),
      'plan' => _PlanCard(card, onChanged: onChanged),
      'orders' => _OrdersCard(card, onChanged: onChanged),
      'plan_detail' => _PlanDetailCard(card),
      _ => const SizedBox.shrink(),
    };
  }

  Widget _frame(Widget body) {
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18), border: Border.all(color: C.line)),
      child: body,
    );
  }
}

/// 카드 머리: 작은 회색 꼬리표 + 큰 제목 + 상태 알약.
class _Head extends StatelessWidget {
  const _Head(this.tag, this.title, {this.pill, this.icon = Icons.article_rounded});
  final String tag;
  final String title;
  final Widget? pill;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(icon, size: 15, color: C.g500),
              const SizedBox(width: 6),
              Flexible(child: Text(tag, style: T.small, overflow: TextOverflow.ellipsis)),
            ]),
            const SizedBox(height: 6),
            Text(title, style: T.h3),
          ]),
        ),
        if (pill != null) ...[const SizedBox(width: 12), pill!],
      ]),
    );
  }
}

Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List<Map<String, dynamic>> _l(dynamic x) => [for (final e in (x as List? ?? const [])) _m(e)];

// ---------- 문서 읽기 (A, B, C) ----------

class _DocCard extends StatefulWidget {
  const _DocCard(this.c, {this.onChanged});
  final Map<String, dynamic> c;
  final VoidCallback? onChanged;
  @override
  State<_DocCard> createState() => _DocCardState();
}

class _DocCardState extends State<_DocCard> {
  bool _handled = false;

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final f = _m(c['fields']);
    final tag = 'Studio ${c['kind']} · ${c['file']}';
    switch (c['kind']) {
      case 'A':
        final pending = Live.reviewPending(c['case_key'], c['review_status'] == 'pending') && !_handled;
        final shownStatus = pending ? f['config_status']?.toString() : (c['review_status'] == 'pending' ? 'approved' : f['config_status']?.toString());
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Head(tag, niceName(c['case_key'].toString()), pill: Pill.of(shownStatus)),
          StatRow([
            BigStat('단계', stageName(f['stage'])),
            BigStat('가동 시작', f['online_month']?.toString() ?? '-'),
            BigStat('한국 계약', '${f['kr_mtpa'] ?? 0}', unit: 'MTPA'),
          ]),
          if ((f['reason'] ?? '').toString().isNotEmpty) ...[const SizedBox(height: 12), Text(f['reason'].toString(), style: T.sub)],
          Details(title: 'Studio 출력 원본', child: RawFields(f)),
          if (pending)
            PrimaryButton('값 확인하고 반영하기', onPressed: () async {
              if (await reviewSheet(context, {'case_key': c['case_key'], ...f})) {
                setState(() => _handled = true);
                widget.onChanged?.call();
              }
            }),
        ]);
      default:
        const issueKeys = ['shortage_rows', 'over_contract_rows', 'capacity_rows', 'safety_rows', 'mismatch_rows'];
        const issueNames = {
          'shortage_rows': '부족',
          'over_contract_rows': '계약 초과',
          'capacity_rows': '용량 초과',
          'safety_rows': '안전재고 미달',
          'mismatch_rows': '합계 불일치'
        };
        final issues = [for (final k in issueKeys) if ((f[k] as List?)?.isNotEmpty ?? false) '${issueNames[k]} ${(f[k] as List).length}건'];
        final agree = c['code_decision'] == null || c['code_decision'] == f['decision'];
        final replan = c['replan'] == null ? null : _m(c['replan']);
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Head(tag, f['plan_id']?.toString() ?? '실행안', pill: Pill.of(f['decision']?.toString())),
          StatRow([
            BigStat('계획 물량', num0(f['total_planned_kt']), unit: 'kt'),
            BigStat('현물', '${f['spot_cargoes'] ?? 0}', unit: '척'),
            BigStat('걸린 항목', '${issues.length}', unit: '종류', color: issues.isEmpty ? null : C.orange),
          ]),
          const SizedBox(height: 12),
          if (issues.isNotEmpty) Text(issues.join(', '), style: T.sub.copyWith(color: C.orange, fontWeight: FontWeight.w600)),
          Text(f['reason']?.toString() ?? '', style: T.sub),
          const SizedBox(height: 6),
          Row(children: [
            Icon(agree ? Icons.check_circle_rounded : Icons.error_rounded, size: 16, color: agree ? C.green : C.orange),
            const SizedBox(width: 6),
            Text(agree ? '코드 검산도 같은 판정이에요' : '코드 검산은 "${label(c['code_decision']?.toString())}"로 달라요', style: T.small),
          ]),
          Details(title: 'Studio 출력 원본', child: RawFields(f)),
          if (replan != null) ...[
            const Divider(height: 24),
            const Text('같은 조건으로 다시 계획했어요', style: T.h3),
            const SizedBox(height: 4),
            _PlanBody(replan, onChanged: widget.onChanged),
          ],
        ]);
    }
  }
}

// ---------- 확인할 일 ----------

class _ReviewsCard extends StatefulWidget {
  const _ReviewsCard(this.c, {this.onChanged});
  final Map<String, dynamic> c;
  final VoidCallback? onChanged;
  @override
  State<_ReviewsCard> createState() => _ReviewsCardState();
}

class _ReviewsCardState extends State<_ReviewsCard> {
  final Set<String> _done = {};

  @override
  Widget build(BuildContext context) {
    final items = _l(widget.c['items']);
    if (items.isEmpty) {
      return const RowItem(icon: Icons.check_rounded, iconColor: C.green, title: '확인할 프로젝트가 없어요', subtitle: '모든 A 결과가 최적화에 들어가 있어요');
    }
    for (final r in items) {
      if (!Live.reviewPending(r['case_key'], true)) _done.add(r['case_key'].toString());
    }
    final left = items.where((r) => !_done.contains(r['case_key'])).length;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head('Studio A 사람 확인', left == 0 ? '모두 처리했어요' : '$left건을 봐주세요', icon: Icons.task_alt_rounded),
      for (final r in items)
        RowItem(
          icon: _done.contains(r['case_key']) ? Icons.check_rounded : Icons.priority_high_rounded,
          iconColor: _done.contains(r['case_key']) ? C.green : C.orange,
          title: niceName(r['case_key'].toString()),
          subtitle: r['reason']?.toString(),
          onTap: _done.contains(r['case_key'])
              ? null
              : () async {
                  if (await reviewSheet(context, r)) {
                    setState(() => _done.add(r['case_key'].toString()));
                    widget.onChanged?.call();
                  }
                },
        ),
    ]);
  }
}

// ---------- 공급 전망 ----------

class _SupplyCard extends StatelessWidget {
  const _SupplyCard(this.c);
  final Map<String, dynamic> c;

  @override
  Widget build(BuildContext context) {
    final items = _l(c['items']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head(c['source']?.toString() ?? '공급 전망', '2027년 말 가동 가능성 높은 곳 ${c['likely']}/${c['total']}',
          icon: Icons.directions_boat_rounded),
      for (final p in items)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(niceName(p['project'].toString()), style: T.body.copyWith(fontSize: 15)),
                Text('${stageName(p['stage'])} · 가동 ${p['online_month'] ?? '-'}${((p['kr_mtpa'] as num?) ?? 0) > 0 ? ' · 한국 ${p['kr_mtpa']} MTPA' : ''}',
                    style: T.small),
              ]),
            ),
            SizedBox(
              width: 120,
              child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text('${(((p['p_2027_12'] as num?) ?? 0) * 100).round()}%', style: T.body.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: ((p['p_2027_12'] as num?) ?? 0).toDouble(),
                    minHeight: 6,
                    backgroundColor: C.g100,
                    color: ((p['p_2027_12'] as num?) ?? 0) >= 0.5 ? C.blue : C.g300,
                  ),
                ),
              ]),
            ),
          ]),
        ),
      if ((c['total'] as num? ?? 0) > items.length)
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('가능성 높은 순으로 ${items.length}곳만 보여줘요', style: T.small)),
    ]);
  }
}

// ---------- 비용 비교 ----------

class _ScenarioCard extends StatelessWidget {
  const _ScenarioCard(this.c);
  final Map<String, dynamic> c;

  @override
  Widget build(BuildContext context) {
    final p = _m(c['procurement']);
    final eff = c['diversification_effect'] is Map ? _m(c['diversification_effect']) : null;
    final rec = _l(p['new_contracts']).where((x) => x['recommended'] == true).toList();
    final mtpa = rec.fold<num>(0, (a, x) => a + ((x['contract_mtpa'] as num?) ?? 0));
    final short = ((c['total_shortage_kt'] as num?) ?? 0);
    final title = rec.isEmpty
        ? '기존 계약과 현물로 조달해요'
        : '미국 신규 ${rec.length}곳과 ${mtpa.toStringAsFixed(1)} MTPA 계약을 권해요';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head('조달 최적화 ${p['period'] ?? ''} · ${scen(c)}', title, icon: Icons.auto_graph_rounded),
      StatRow([
        BigStat('5년 총비용', num0(c['total_cost_musd']), unit: 'M\$'),
        BigStat('현물 카고', num0(c['spot_cargoes']), unit: '척'),
        BigStat('부족', num0(short), unit: 'kt', color: short > 0 ? C.red : null),
      ]),
      const SizedBox(height: 20),
      if (p.isNotEmpty) ProcurementView(p, effect: eff),
    ]);
  }
}

// ---------- 계획 ----------

class _PlanCard extends StatelessWidget {
  const _PlanCard(this.c, {this.onChanged});
  final Map<String, dynamic> c;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) => _PlanBody(c, onChanged: onChanged, head: true);
}

class _PlanBody extends StatefulWidget {
  const _PlanBody(this.c, {this.onChanged, this.head = false});
  final Map<String, dynamic> c;
  final VoidCallback? onChanged;
  final bool head;
  @override
  State<_PlanBody> createState() => _PlanBodyState();
}

class _PlanBodyState extends State<_PlanBody> {
  bool _approved = false;

  @override
  Widget build(BuildContext context) {
    final c = widget.c;
    final order = _m(c['order']);
    final check = _m(order['studio_check']);
    final history = _l(c['history']);
    final purchases = _l(c['purchase_requests']);
    final spot = purchases.where((p) => p['source'] == 'SPOT').fold<num>(0, (a, p) => a + ((p['cargoes'] as num?) ?? 0));
    final status = _approved ? 'APPROVED' : Live.orderStatus(order['order_id'], c['status']);
    final shortage = [for (final s in (check['shortage_rows'] as List? ?? const [])) s.toString()];
    final months = (order['months'] as List?) ?? const [];
    final title = switch (status) {
      'PENDING_APPROVAL' => '승인할 준비가 됐어요',
      'APPROVED' => '승인했어요',
      'NEEDS_REVIEW' => 'Studio와 코드 판정이 달라요',
      _ => '다시 계획해도 문제가 남았어요',
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (widget.head)
        _Head('계획 초안 · ${months.isEmpty ? '' : '${months.first} ~ ${months.last}'} · ${scen(order)}', title,
            pill: Pill.of(status), icon: Icons.receipt_long_rounded),
      StatRow([
        BigStat('3개월 물량', num0(check['total_planned_kt']), unit: 'kt'),
        BigStat('현물 구매', num0(spot), unit: '척'),
        BigStat('실행안', '${history.length}', unit: '번 작성'),
      ]),
      const SizedBox(height: 8),
      if (shortage.isNotEmpty)
        RowItem(
          icon: Icons.warning_rounded,
          iconColor: C.red,
          title: '현물로도 못 채우는 달이 있어요',
          subtitle: shortage.map((s) => '${s.split(',').first} ${num0(s.split(',').last)} kt').join(', '),
        ),
      for (final h in history)
        RowItem(
          icon: Icons.picture_as_pdf_rounded,
          iconColor: h['studio_decision'] == '승인 요청' ? C.green : C.orange,
          title: '${h['attempt']}번째 실행안 · ${label(h['studio_decision']?.toString())}',
          subtitle: 'Studio C ${h['studio_decision']} / 코드 검산 ${h['code_decision']}',
          onTap: () => openUrl(Api.instance.fileUrl(h['pdf'].toString())),
        ),
      if (order['procurement'] is Map && _m(order['procurement']).isNotEmpty)
        Details(title: '5년 조달 계획 보기 (신규 계약 권장, 연도별 구성)', child: ProcurementView(_m(order['procurement']))),
      if (order['order_id'] != null) ...[
        const SizedBox(height: 8),
        SecondaryButton('상세 보기', onPressed: () => planDetailSheet(context, order['order_id'].toString())),
      ],
      if (status == 'PENDING_APPROVAL' && order['order_id'] != null) ...[
        const SizedBox(height: 8),
        PrimaryButton('검토하고 승인하기', onPressed: () async {
          if (await orderSheet(context, order['order_id'].toString())) {
            setState(() => _approved = true);
            widget.onChanged?.call();
          }
        }),
      ],
    ]);
  }
}

class _OrdersCard extends StatelessWidget {
  const _OrdersCard(this.c, {this.onChanged});
  final Map<String, dynamic> c;
  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    final items = _l(c['items']);
    final pending = items.where((o) => o['status'] == 'PENDING_APPROVAL').length;
    if (items.isEmpty) {
      return const RowItem(icon: Icons.inbox_rounded, iconColor: C.g500, title: '아직 계획 초안이 없어요', subtitle: '계획을 세워 달라고 말해 보세요');
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head('계획 초안', pending == 0 ? '승인할 계획이 없어요' : '승인할 계획이 $pending건 있어요', icon: Icons.verified_rounded),
      for (final o in items) OrderRow(o, onDone: onChanged),
    ]);
  }
}

// ---------- 수급 현황 요약 ----------

class _OverviewCard extends StatelessWidget {
  const _OverviewCard(this.c);
  final Map<String, dynamic> c;

  @override
  Widget build(BuildContext context) {
    final d = c['demand_plan'] is Map ? _m(c['demand_plan']) : null;
    final us = _m(c['us_supply_A']);
    final wait = _m(c['waiting_for_people']);
    final annual = _m(d?['annual_demand_kt']);
    final years = annual.keys.toList()..sort();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head(d == null ? '수요 기준 자료 없음' : '수요 기준: ${d['plan']} · ${d['period']}', '한국 LNG 수급 현황', icon: Icons.insights_rounded),
      if (d != null) ...[
        const Text('수요 목표 (도시가스 + 발전)', style: T.small),
        const SizedBox(height: 8),
        StatRow([for (final y in years.take(3)) BigStat('$y년', num0(_m(annual[y])['total']), unit: 'kt')]),
        const SizedBox(height: 8),
        Text('저장 기지 ${d['terminals']}곳, 용량 합계 ${num0(d['terminal_capacity_kt_total'])} kt', style: T.sub),
        const Divider(height: 28),
      ] else
        const Padding(padding: EdgeInsets.only(bottom: 12), child: Text('수요 기준 자료가 없어요', style: T.sub)),
      const Text('미국 프로젝트 (Studio A)', style: T.small),
      const SizedBox(height: 8),
      StatRow([
        BigStat('반영된 프로젝트', '${us['projects'] ?? 0}', unit: '곳'),
        BigStat('2027년 말 가동 유력', '${us['likely_online_by_2027_12'] ?? 0}', unit: '곳'),
        BigStat('한국 계약', '${us['korean_contract_mtpa_total'] ?? 0}', unit: 'MTPA'),
      ]),
      const Divider(height: 28),
      RowItem(
        icon: Icons.task_alt_rounded,
        iconColor: ((wait['reviews'] as num?) ?? 0) > 0 ? C.orange : C.green,
        title: '확인할 프로젝트 ${wait['reviews'] ?? 0}건',
      ),
      RowItem(
        icon: Icons.verified_rounded,
        iconColor: ((wait['orders_pending_approval'] as num?) ?? 0) > 0 ? C.blue : C.green,
        title: '승인 대기 계획 ${wait['orders_pending_approval'] ?? 0}건',
        subtitle: ((wait['orders_needing_review'] as num?) ?? 0) > 0 ? '사람 확인이 필요한 계획 ${wait['orders_needing_review']}건' : null,
      ),
    ]);
  }
}

class _PlanDetailCard extends StatelessWidget {
  const _PlanDetailCard(this.c);
  final Map<String, dynamic> c;

  @override
  Widget build(BuildContext context) {
    final tot = _m(c['purchase_total']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Head('배분 상세 · ${scen(c)}', '추가 구매 ${tot['cargoes']}척, ${num0(tot['cost_musd'])}M\$',
          pill: Pill.of(Live.orderStatus(c['order_id'], c['status'])), icon: Icons.local_shipping_rounded),
      PlanDetailView(c),
    ]);
  }
}
