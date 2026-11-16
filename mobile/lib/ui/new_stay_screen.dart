import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/format.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';

/// «Забронировать»: a guest who phoned or walked in. Dates first, then the free rooms (cars, halls) for all of
/// them, the guests and the customer. Closes with the new [Stay]; the server keeps the AI's rules.
class NewStayScreen extends StatefulWidget {
  const NewStayScreen({super.key, required this.kind, required this.today});

  /// room | car | hall
  final String kind;
  final DateTime today;

  @override
  State<NewStayScreen> createState() => _NewStayScreenState();
}

class _NewStayScreenState extends State<NewStayScreen> {
  final _name = TextEditingController();
  final _phone = TextEditingController();
  late DateTime _checkIn = DateTime(widget.today.year, widget.today.month, widget.today.day);
  int _nights = 1;
  int _guests = 1;
  List<FreeRoom>? _rooms;
  int? _roomId;
  String? _error;
  bool _saving = false;
  int _asked = 0; // only the latest dates' answer is shown

  bool get _hall => widget.kind == 'hall';
  DateTime get _checkOut => _checkIn.add(Duration(days: _hall ? 1 : _nights));

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final asked = ++_asked;
    setState(() => _rooms = null);
    try {
      final rooms = await context.read<JoopRepository>().freeRooms(_checkIn, _checkOut);
      if (!mounted || asked != _asked) return;
      setState(() {
        _rooms = rooms;
        if (!rooms.any((r) => r.id == _roomId && r.free > 0)) _roomId = null;
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted && asked == _asked) setState(() => (_rooms = const [], _error = e.message));
    }
  }

  void _dates({int days = 0, int nights = 0}) {
    final today = DateTime(widget.today.year, widget.today.month, widget.today.day);
    final next = _checkIn.add(Duration(days: days));
    if (next.isBefore(today) || _nights + nights < 1 || _nights + nights > 30) return;
    setState(() => (_checkIn = next, _nights = _nights + nights));
    _load();
  }

  Future<void> _save() async {
    final room = _roomId;
    if (room == null) return;
    setState(() => (_saving = true, _error = null));
    try {
      final stay = await context.read<JoopRepository>().newStay(
          roomId: room, checkIn: _checkIn, checkOut: _checkOut, guests: _guests, name: _name.text, phone: _phone.text);
      if (mounted) Navigator.of(context).pop(stay);
    } on ApiException catch (e) {
      if (mounted) setState(() => (_saving = false, _error = e.message));
    }
  }

  /// One more guest still fits the chosen room (checked again on each tap: two quick taps see the same button).
  bool _roomFits(FreeRoom? room) => room == null || room.capacity == 0 || _guests < room.capacity;

  @override
  Widget build(BuildContext context) {
    final s = S.current;
    final theme = Theme.of(context);
    final today = DateTime(widget.today.year, widget.today.month, widget.today.day);
    final chosen = _rooms?.where((r) => r.id == _roomId).firstOrNull;
    // the label and the value on the left, the buttons always on screen: «вт, 17 ноя – чт, 19 ноя» is wide on a phone
    Widget stepper(String label, String value, VoidCallback? less, VoidCallback? more, String key) => Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: theme.textTheme.labelLarge),
              Text(value, key: Key(key), style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            ]),
          ),
          IconButton(key: Key('$key-less'), onPressed: less, icon: const Icon(Icons.remove_circle_outline)),
          IconButton(key: Key('$key-more'), onPressed: more, icon: const Icon(Icons.add_circle_outline)),
        ]);
    return Scaffold(
      appBar: AppBar(title: Text(s.newStay, style: const TextStyle(fontWeight: FontWeight.w800))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          stepper(_hall ? s.stayDate : s.stayCheckIn, formatDay(_checkIn),
              _checkIn.isAfter(today) ? () => _dates(days: -1) : null, () => _dates(days: 1), 'stay-day'),
          if (!_hall)
            stepper(widget.kind == 'car' ? s.stayDays(_nights) : s.stayNights(_nights),
                '${formatDay(_checkIn)} – ${formatDay(_checkOut)}',
                _nights > 1 ? () => _dates(nights: -1) : null, _nights < 30 ? () => _dates(nights: 1) : null, 'stay-nights'),
          const SizedBox(height: 12),
          Text(s.chooseRoom(widget.kind), style: theme.textTheme.labelLarge),
          const SizedBox(height: 8),
          switch (_rooms) {
            null => const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
            final rooms when rooms.every((r) => r.free == 0) =>
              Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(s.noRoomsFree)),
            final rooms => Wrap(spacing: 8, runSpacing: 8, children: [
                for (final r in rooms)
                  ChoiceChip(
                    key: Key('stay-room-${r.id}'),
                    label: Text('${r.name} · ${s.roomFree(r.free)}'),
                    selected: r.id == _roomId,
                    onSelected: r.free == 0 ? null : (_) => setState(() => (_roomId = r.id, _guests = 1)),
                  ),
              ]),
          },
          if (widget.kind != 'car') ...[
            const SizedBox(height: 8),
            stepper(s.guestsLabel, '$_guests', _guests > 1 ? () => setState(() => _guests--) : null,
                _roomFits(chosen) ? () => setState(() => _guests += _roomFits(chosen) ? 1 : 0) : null, 'stay-guests'),
          ],
          const SizedBox(height: 12),
          TextField(
            key: const Key('stay-name'),
            controller: _name,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(labelText: s.customerName),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('stay-phone'),
            controller: _phone,
            keyboardType: TextInputType.phone,
            decoration: InputDecoration(labelText: s.customerPhoneOptional, hintText: '0555 123 456'),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, key: const Key('stay-error'), style: TextStyle(color: theme.colorScheme.error)),
          ],
          const SizedBox(height: 20),
          FilledButton(
            key: const Key('stay-save'),
            onPressed: _roomId == null || _saving ? null : _save,
            child: _saving
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : Text(s.newStay),
          ),
        ],
      ),
    );
  }
}
