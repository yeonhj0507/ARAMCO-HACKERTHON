import 'package:flutter/material.dart';

import 'api.dart';
import 'plan_detail.dart';
import 'theme.dart';
import 'widgets.dart';

/// 사람이 하는 일 (반영, 제외, 승인). 채팅 카드와 바로 보기 화면이 같이 쓴다.
class Me {
  static String name = '담당자';
}

/// 서버의 최신 상태. 채팅 카드는 도구를 부른 순간의 결과라서, 나중에 승인하거나 반영하면
/// 카드가 옛 상태로 남는다. 카드는 여기 값을 먼저 보고, 없을 때만 카드에 담긴 값을 쓴다.
class Live {
  static final orders = ValueNotifier<Map<String, String>>({});
  static final pendingReviews = ValueNotifier<Set<String>?>(null);

  static Future<void> refresh() async {
    try {
      final o = await Api.instance.get('/orders');
      orders.value = {for (final x in o as List) x['order_id'].toString(): x['status'].toString()};
      final r = await Api.instance.get('/reviews');
      pendingReviews.value = {for (final x in r as List) x['case_key'].toString()};
    } catch (_) {}
  }

  static String? orderStatus(dynamic id, dynamic fallback) => orders.value[id?.toString()] ?? fallback?.toString();
  static bool reviewPending(dynamic key, bool fallback) => pendingReviews.value?.contains(key?.toString()) ?? fallback;
}

const stageNames = {'pre_fid': '착공 전', 'construction': '건설 중', 'commissioning': '시운전', 'operating': '생산 중'};
String stageName(dynamic s) => stageNames[s?.toString()] ?? (s?.toString() ?? '-');

Future<T?> _sheet<T>(BuildContext context, WidgetBuilder builder) => showModalBottomSheet<T>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      constraints: const BoxConstraints(maxWidth: 720),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: builder,
    );

/// Studio A가 확인으로 넘긴 프로젝트: 그대로 반영, 고쳐서 반영, 제외. 처리했으면 true.
Future<bool> reviewSheet(BuildContext context, Map<String, dynamic> r) async {
  final edits = <String, TextEditingController>{
    for (final k in ['docket', 'stage', 'online_month', 'kr_mtpa']) k: TextEditingController(text: '${r[k] ?? ''}'),
  };
  bool operating = r['operating'] == true;
  final result = await _sheet<String>(
    context,
    (c) => StatefulBuilder(
      builder: (c, setS) => Padding(
        padding: EdgeInsets.fromLTRB(28, 28, 28, 28 + MediaQuery.of(c).viewInsets.bottom),
        child: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            Text(niceName(r['case_key'].toString()), style: T.h2),
            const SizedBox(height: 8),
            Text(r['reason']?.toString() ?? '', style: T.sub),
            const SizedBox(height: 20),
            const Text('원문을 보고 값이 틀렸으면 고쳐주세요', style: T.h3),
            const SizedBox(height: 4),
            const Text('고친 값과 Studio가 낸 값이 둘 다 기록에 남아요.', style: T.small),
            const SizedBox(height: 12),
            for (final e in edits.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: TextField(
                  controller: e.value,
                  decoration: InputDecoration(
                    labelText: {
                      'docket': '도켓 번호',
                      'stage': '단계 (pre_fid, construction, commissioning, operating)',
                      'online_month': '가동 시작 (YYYY-MM)',
                      'kr_mtpa': '한국 계약 물량 (MTPA)'
                    }[e.key],
                    filled: true,
                    fillColor: C.g100,
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                  ),
                ),
              ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('이미 LNG를 생산하고 있어요', style: T.body),
              value: operating,
              onChanged: (v) => setS(() => operating = v),
            ),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: SecondaryButton('빼둘게요', onPressed: () => Navigator.pop(c, 'reject'))),
              const SizedBox(width: 12),
              Expanded(flex: 2, child: PrimaryButton('반영할게요', onPressed: () => Navigator.pop(c, 'approve'))),
            ]),
          ]),
        ),
      ),
    ),
  );
  if (result == null || !context.mounted) return false;
  try {
    final key = r['case_key'];
    if (result == 'reject') {
      await Api.instance.post('/reviews/$key/reject', {'approver': Me.name});
      if (context.mounted) toast(context, '최적화에서 뺐어요');
    } else {
      final overrides = <String, dynamic>{};
      for (final e in edits.entries) {
        if (e.value.text != '${r[e.key] ?? ''}') overrides[e.key] = e.value.text;
      }
      if (operating != (r['operating'] == true)) overrides['operating'] = '$operating';
      await Api.instance.post('/reviews/$key/approve', {'approver': Me.name, 'overrides': overrides});
      if (context.mounted) {
        toast(context, overrides.isEmpty ? '그대로 반영했어요' : '고친 값으로 반영했어요 (${overrides.keys.join(', ')})');
      }
    }
    await Live.refresh();
    return true;
  } catch (e) {
    if (context.mounted) showError(context, e);
    return false;
  }
}

/// 계획 초안을 열어 보고 승인한다. 승인했으면 true.
Future<bool> orderSheet(BuildContext context, String id) async {
  Map<String, dynamic>? loaded;
  try {
    loaded = Map<String, dynamic>.from(await Api.instance.get('/orders/$id'));
  } catch (e) {
    if (context.mounted) showError(context, e);
  }
  if (loaded == null || !context.mounted) return false;
  final o = loaded;
  final check = Map<String, dynamic>.from(o['studio_check'] ?? {});
  final purchases = [for (final p in (o['purchase_requests'] as List? ?? [])) Map<String, dynamic>.from(p)];
  final spot = purchases.where((p) => p['source'] == 'SPOT').fold<num>(0, (a, p) => a + ((p['cargoes'] as num?) ?? 0));
  final replan = o['replan_of'] as Map?;
  final months = (o['months'] as List?) ?? const [];
  final go = await _sheet<bool>(
    context,
    (c) => Padding(
      padding: const EdgeInsets.all(28),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Expanded(child: Text(months.isEmpty ? '계획 초안' : '${months.first} ~ ${months.last} 배분', style: T.h2)),
            Pill.of(o['status']?.toString()),
          ]),
          const SizedBox(height: 6),
          Text(scen(o), style: T.sub),
          const SizedBox(height: 20),
          if (check.isEmpty)
            Container(
              margin: const EdgeInsets.only(bottom: 16),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: C.redLight, borderRadius: BorderRadius.circular(14)),
              child: const Text('Studio C 검사 없이 만든 예전 방식 초안이에요. 승인할 수 없어요.\n대화에서 "계획 세워줘"라고 하면 검사까지 거친 계획을 다시 만들어요.',
                  style: T.sub),
            ),
          if (replan != null)
            Container(
              margin: const EdgeInsets.only(bottom: 16),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: C.orangeLight, borderRadius: BorderRadius.circular(14)),
              child: Text('${replan['file']}이 검사에서 걸려서 다시 세운 계획이에요.\n걸린 항목: ${fmt(replan['violations'])}', style: T.sub),
            ),
          StatRow([
            BigStat('계획 물량', num0(check['total_planned_kt']), unit: 'kt'),
            BigStat('현물 구매', num0(spot), unit: '척'),
            BigStat('구매 요청', '${purchases.length}', unit: '건'),
          ]),
          const SizedBox(height: 16),
          Text(check['reason']?.toString() ?? '', style: T.sub),
          Details(title: 'Studio C 검사 결과 보기', child: RawFields(check)),
          if (check.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: SecondaryButton('상세 보기', onPressed: () => planDetailSheet(c, id)),
            ),
          const SizedBox(height: 12),
          if (o['status'] == 'PENDING_APPROVAL' && check['decision'] == '승인 요청') ...[
            TextFormField(
              initialValue: Me.name,
              decoration: const InputDecoration(labelText: '승인하는 사람', isDense: true),
              onChanged: (v) => Me.name = v,
            ),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: SecondaryButton('닫기', onPressed: () => Navigator.pop(c, false))),
              const SizedBox(width: 12),
              Expanded(flex: 2, child: PrimaryButton('승인하기', onPressed: () => Navigator.pop(c, true))),
            ]),
          ] else
            SecondaryButton('닫기', onPressed: () => Navigator.pop(c, false)),
        ]),
      ),
    ),
  );
  if (go != true || !context.mounted) return false;
  try {
    await Api.instance.post('/orders/$id/approve', {'approver': Me.name});
    await Live.refresh();
    if (context.mounted) toast(context, '승인했어요. 배분 지시와 구매 요청이 확정됐어요.');
    return true;
  } catch (e) {
    if (context.mounted) showError(context, e);
    return false;
  }
}
