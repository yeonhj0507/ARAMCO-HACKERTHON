import 'package:flutter/material.dart';

import 'actions.dart';
import 'api.dart';
import 'pages/approve_page.dart';
import 'pages/chat_page.dart';
import 'pages/check_page.dart';
import 'pages/plan_page.dart';
import 'pages/read_page.dart';
import 'pages/supply_page.dart';
import 'theme.dart';
import 'title_bar.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await setupWindow();
  runApp(const LngAgentApp());
}

class LngAgentApp extends StatelessWidget {
  const LngAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'LNG 수급 에이전트',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const Shell(),
    );
  }
}

class _Tab {
  const _Tab(this.label, this.icon);
  final String label;
  final IconData icon;
}

// 0번이 기본 화면인 대화. 나머지는 직접 볼 때 쓰는 화면.
const _tabs = [
  _Tab('대화', Icons.forum_rounded),
  _Tab('확인할 일', Icons.task_alt_rounded),
  _Tab('승인', Icons.verified_rounded),
  _Tab('공급 전망', Icons.directions_boat_rounded),
  _Tab('문서 읽기', Icons.article_rounded),
  _Tab('계획 세우기', Icons.auto_graph_rounded),
];

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _i = 0;
  int _chat = 0; // 새 대화를 누를 때마다 바뀐다
  Map<String, dynamic>? _status;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    Live.refresh();
    try {
      final s = Map<String, dynamic>.from(await Api.instance.get('/status'));
      if (mounted) setState(() => _status = s);
    } catch (_) {}
  }

  void go(int i) {
    setState(() => _i = i);
    _refresh();
  }

  void _newChat() {
    ChatPage.reset();
    setState(() {
      _chat++;
      _i = 0;
    });
  }

  int _badge(int i) => switch (i) {
        1 => ((_status?['a_params']?['pending'] as num?) ?? 0).toInt(),
        2 => ((_status?['orders']?['pending'] as num?) ?? 0).toInt(),
        _ => 0,
      };

  Widget _page() => switch (_i) {
        0 => ChatPage(key: ValueKey('chat$_chat'), onChanged: _refresh),
        1 => CheckPage(onChanged: _refresh),
        2 => ApprovePage(onChanged: _refresh),
        3 => const SupplyPage(),
        4 => const ReadPage(),
        _ => PlanPage(onGo: go),
      };

  Widget _item(int i) {
    final on = i == _i;
    final b = _badge(i);
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => go(i),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(color: on ? C.blueLight : Colors.transparent, borderRadius: BorderRadius.circular(12)),
          child: Row(children: [
            Icon(_tabs[i].icon, size: 20, color: on ? C.blue : C.g500),
            const SizedBox(width: 12),
            Expanded(
              child: Text(_tabs[i].label,
                  style: T.body.copyWith(fontSize: 15, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? C.blue : C.g700)),
            ),
            if (b > 0)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                decoration: BoxDecoration(color: i == 1 ? C.orange : C.blue, borderRadius: BorderRadius.circular(10)),
                child: Text('$b', style: T.small.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
              ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(children: [
        if (isDesktop) const TitleBar(),
        Expanded(child: Row(children: [
        Container(
          width: 232,
          color: Colors.white,
          padding: const EdgeInsets.fromLTRB(16, 28, 16, 16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.only(left: 12, bottom: 24),
              child: Row(children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(color: C.blue, borderRadius: BorderRadius.circular(10)),
                  child: const Icon(Icons.local_fire_department_rounded, color: Colors.white, size: 20),
                ),
                const SizedBox(width: 10),
                const Text('LNG 수급', style: T.h3),
              ]),
            ),
            OutlinedButton.icon(
              onPressed: _newChat,
              icon: const Icon(Icons.add_rounded, size: 20),
              label: const Text('새 대화'),
              style: OutlinedButton.styleFrom(
                foregroundColor: C.g900,
                side: const BorderSide(color: C.line),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                textStyle: T.body.copyWith(fontSize: 15, fontWeight: FontWeight.w600),
              ),
            ),
            const SizedBox(height: 16),
            _item(0),
            const Padding(padding: EdgeInsets.fromLTRB(12, 20, 12, 8), child: Text('직접 보기', style: T.small)),
            for (var i = 1; i < _tabs.length; i++) _item(i),
            const Spacer(),
            const Padding(
              padding: EdgeInsets.only(left: 12),
              child: Text('Upstage Studio × 배분 최적화', style: T.small),
            ),
          ]),
        ),
        Expanded(child: KeyedSubtree(key: ValueKey('page$_i'), child: _page())),
      ])),
      ]),
    );
  }
}
