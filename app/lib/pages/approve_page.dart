import 'package:flutter/material.dart';

import '../actions.dart';
import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// 바로 보기: 계획 초안. Studio C가 문제 없다고 본 계획만 승인할 수 있다.
class ApprovePage extends StatefulWidget {
  const ApprovePage({super.key, this.onChanged});
  final VoidCallback? onChanged;
  @override
  State<ApprovePage> createState() => _ApprovePageState();
}

class _ApprovePageState extends State<ApprovePage> {
  List<Map<String, dynamic>>? _orders;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Api.instance.get('/orders');
      setState(() => _orders = [for (final x in r as List) Map<String, dynamic>.from(x)]);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final all = _orders ?? [];
    final pending = all.where((o) => o['status'] == 'PENDING_APPROVAL').toList();
    final needs = all.where((o) => o['status'] == 'NEEDS_REVIEW' || o['status'] == 'ESCALATED').toList();
    final doneList = all.where((o) => o['status'] == 'APPROVED').toList();

    Widget list(List<Map<String, dynamic>> xs) => Box(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(children: [for (final o in xs) OrderRow(o, onDone: () async {
            await _load();
            widget.onChanged?.call();
          })]),
        );

    return PageScaffold(
      title: _orders == null
          ? '불러오는 중이에요'
          : pending.isEmpty
              ? '승인할 계획이 없어요'
              : '승인할 계획이 ${pending.length}건 있어요',
      subtitle: '검증 시스템이 문제 없다고 본 계획만 승인할 수 있어요. 에이전트는 초안까지만 만들어요.',
      children: [
        if (pending.isNotEmpty) list(pending),
        if (needs.isNotEmpty) ...[const SizedBox(height: 8), const Text('사람 확인이 필요해요', style: T.h3), const SizedBox(height: 12), list(needs)],
        if (doneList.isNotEmpty) ...[const SizedBox(height: 8), const Text('승인한 계획', style: T.h3), const SizedBox(height: 12), list(doneList)],
      ],
    );
  }
}

/// 계획 초안 한 줄. 누르면 열어 보고 승인한다.
class OrderRow extends StatelessWidget {
  const OrderRow(this.o, {super.key, this.onDone});
  final Map<String, dynamic> o;
  final VoidCallback? onDone;

  @override
  Widget build(BuildContext context) {
    final months = (o['months'] as List?) ?? const [];
    return RowItem(
      icon: o['replan_of'] != null ? Icons.autorenew_rounded : Icons.receipt_long_rounded,
      iconColor: toneOf(o['status']?.toString()) == Tone.warn ? C.orange : C.blue,
      title: '${months.isEmpty ? '' : '${months.first} ~ ${months.last}'} · ${scen(o)}',
      subtitle: o['studio_checked'] == false ? '검증 안 됨 (예전 방식 초안)' : o['reason']?.toString(),
      trailing: o['studio_checked'] == false
          ? const Pill('검사 없음', tone: Tone.bad)
          : Pill.of(Live.orderStatus(o['order_id'], o['status'])),
      onTap: () async {
        if (await orderSheet(context, o['order_id'].toString())) onDone?.call();
      },
    );
  }
}
