import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'theme.dart';

/// 데스크톱(Windows)에서만 기본 제목 표시줄을 숨기고 직접 그린 표시줄을 쓴다. 웹에서는 아무것도 하지 않는다.
bool get isDesktop => !kIsWeb && (Platform.isWindows || Platform.isMacOS || Platform.isLinux);

Future<void> setupWindow() async {
  if (!isDesktop) return;
  await windowManager.ensureInitialized();
  const options = WindowOptions(
    size: Size(1380, 880),
    minimumSize: Size(1040, 680),
    center: true,
    title: 'LNG 수급 에이전트',
    titleBarStyle: TitleBarStyle.hidden,
  );
  await windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.show();
    await windowManager.focus();
  });
}

const _barColor = Color(0xFFE6E9ED);

/// 디스코드처럼 얇은 상단 표시줄: 왼쪽 앱 이름, 빈 곳은 끌어서 창 이동(두 번 누르면 최대화), 오른쪽 창 버튼.
class TitleBar extends StatefulWidget {
  const TitleBar({super.key});
  @override
  State<TitleBar> createState() => _TitleBarState();
}

class _TitleBarState extends State<TitleBar> with WindowListener {
  bool _max = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    windowManager.isMaximized().then((v) {
      if (mounted) setState(() => _max = v);
    });
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  void onWindowMaximize() => setState(() => _max = true);
  @override
  void onWindowUnmaximize() => setState(() => _max = false);

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 30,
      color: _barColor,
      child: Row(children: [
        Expanded(
          child: DragToMoveArea(
            child: Container(
              color: Colors.transparent,
              padding: const EdgeInsets.only(left: 14),
              alignment: Alignment.centerLeft,
              child: Row(children: [
                Container(
                  width: 16,
                  height: 16,
                  decoration: BoxDecoration(color: C.blue, borderRadius: BorderRadius.circular(5)),
                  child: const Icon(Icons.local_fire_department_rounded, color: Colors.white, size: 11),
                ),
                const SizedBox(width: 8),
                Text('LNG 수급 에이전트', style: T.small.copyWith(fontWeight: FontWeight.w700, color: C.g700, fontSize: 12)),
              ]),
            ),
          ),
        ),
        _Btn(icon: Icons.remove_rounded, onTap: () => windowManager.minimize()),
        _Btn(
          icon: _max ? Icons.filter_none_rounded : Icons.crop_square_rounded,
          size: _max ? 13 : 15,
          onTap: () async => _max ? windowManager.unmaximize() : windowManager.maximize(),
        ),
        _Btn(icon: Icons.close_rounded, danger: true, onTap: () => windowManager.close()),
      ]),
    );
  }
}

class _Btn extends StatefulWidget {
  const _Btn({required this.icon, required this.onTap, this.danger = false, this.size = 16});
  final IconData icon;
  final VoidCallback onTap;
  final bool danger;
  final double size;
  @override
  State<_Btn> createState() => _BtnState();
}

class _BtnState extends State<_Btn> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final bg = !_hover ? Colors.transparent : (widget.danger ? const Color(0xFFE81123) : const Color(0x14000000));
    final fg = _hover && widget.danger ? Colors.white : C.g700;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 100),
          width: 46,
          height: 30,
          color: bg,
          child: Icon(widget.icon, size: widget.size, color: fg),
        ),
      ),
    );
  }
}
