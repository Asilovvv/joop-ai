import 'package:flutter/material.dart';

/// A QR code the server has already encoded (rows of 0/1): drawn black on white with the four-module quiet zone
/// scanners need, whatever the app's theme.
class QrCode extends StatelessWidget {
  const QrCode({super.key, required this.rows, this.size = 200});

  final List<String> rows;
  final double size;

  @override
  Widget build(BuildContext context) => Semantics(
        label: 'QR',
        image: true,
        child: SizedBox.square(dimension: size, child: CustomPaint(painter: _QrPainter(rows))),
      );
}

class _QrPainter extends CustomPainter {
  _QrPainter(this.rows);

  final List<String> rows;
  static const _quiet = 4;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = Colors.white);
    final cells = rows.length + 2 * _quiet;
    final cell = size.shortestSide / cells;
    final dark = Paint()
      ..color = Colors.black
      ..isAntiAlias = false;
    for (var y = 0; y < rows.length; y++) {
      for (var x = 0; x < rows[y].length; x++) {
        if (rows[y].codeUnitAt(x) == 0x31) {
          // a hair wider than the cell, so no seams show between neighbours
          canvas.drawRect(Rect.fromLTWH((x + _quiet) * cell, (y + _quiet) * cell, cell + 0.5, cell + 0.5), dark);
        }
      }
    }
  }

  @override
  bool shouldRepaint(_QrPainter old) => old.rows != rows;
}
