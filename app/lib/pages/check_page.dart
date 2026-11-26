import 'package:flutter/material.dart';

import '../actions.dart';
import '../api.dart';
import '../theme.dart';
import '../widgets.dart';

/// 바로 보기: Studio A가 사람 확인으로 넘긴 프로젝트.
class CheckPage extends StatefulWidget {
  const CheckPage({super.key, this.onChanged});
  final VoidCallback? onChanged;
  @override
  State<CheckPage> createState() => _CheckPageState();
}

class _CheckPageState extends State<CheckPage> {
  List<Map<String, dynamic>>? _items;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Api.instance.get('/reviews');
      setState(() => _items = [for (final x in r as List) Map<String, dynamic>.from(x)]);
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    return PageScaffold(
      title: items == null
          ? '불러오는 중이에요'
          : items.isEmpty
              ? '확인할 일이 없어요'
              : '확인이 필요한 프로젝트가\n${items.length}건 있어요',
      subtitle: '도켓이 다르거나, 값을 못 읽었거나, 개발이 중단됐는데 한국 계약이 남은 건은 사람이 봐야 최적화에 들어가요.',
      children: [
        if (items != null && items.isNotEmpty)
          Box(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            child: Column(children: [
              for (final r in items)
                RowItem(
                  icon: Icons.priority_high_rounded,
                  iconColor: C.orange,
                  title: niceName(r['case_key'].toString()),
                  subtitle: r['reason']?.toString(),
                  onTap: () async {
                    if (await reviewSheet(context, r)) {
                      await _load();
                      widget.onChanged?.call();
                    }
                  },
                ),
            ]),
          ),
        if (items != null && items.isEmpty)
          const Box(
            child: RowItem(
              icon: Icons.check_rounded,
              iconColor: C.green,
              title: '모든 프로젝트가 반영됐어요',
              subtitle: '새 보고서를 읽으면 여기에 다시 나타나요',
            ),
          ),
      ],
    );
  }
}
