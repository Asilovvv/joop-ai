import 'package:flutter/material.dart';

/// Joop's accent, the same green as the web panel.
const brandColor = Color(0xFF0B7563);
const brandDark = Color(0xFF07413A);

const brandGradient = LinearGradient(
  begin: Alignment.topLeft,
  end: Alignment.bottomRight,
  colors: [brandColor, brandDark],
);

ThemeData buildTheme(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(seedColor: brandColor, brightness: brightness);
  final isLight = brightness == Brightness.light;
  final background = isLight ? const Color(0xFFF4F7F6) : scheme.surface;
  return ThemeData(
    useMaterial3: true,
    fontFamily: 'Roboto',
    colorScheme: scheme,
    scaffoldBackgroundColor: background,
    appBarTheme: AppBarTheme(backgroundColor: background, surfaceTintColor: Colors.transparent, scrolledUnderElevation: 0),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: cardColor(scheme),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: scheme.outlineVariant)),
      enabledBorder:
          OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: scheme.outlineVariant)),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}

Color cardColor(ColorScheme scheme) =>
    scheme.brightness == Brightness.light ? Colors.white : scheme.surfaceContainerHigh;

/// Colour of the channel a booking came from.
Color channelColor(String channel) => switch (channel) {
      'whatsapp' => const Color(0xFF25A244),
      'telegram' => const Color(0xFF229ED9),
      'instagram' => const Color(0xFFD6409F),
      'web' => brandColor,
      _ => const Color(0xFF6F7B79),
    };
