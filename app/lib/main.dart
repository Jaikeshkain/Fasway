import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'core/app_state.dart';
import 'ui/common.dart';
import 'ui/connect_screen.dart';
import 'ui/home_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    systemNavigationBarColor: Color(0xFF0C0E12),
  ));
  final state = await AppState.load();
  runApp(FaswayApp(state));
}

class FaswayApp extends StatelessWidget {
  const FaswayApp(this.state, {super.key});
  final AppState state;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Fasway',
        debugShowCheckedModeBanner: false,
        theme: faswayTheme(),
        home: ListenableBuilder(
          listenable: state,
          builder: (_, _) => state.laptop == null ? ConnectScreen(state) : HomeScreen(state),
        ),
      );
}
