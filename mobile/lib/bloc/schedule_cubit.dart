import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class ScheduleState extends Equatable {
  const ScheduleState({
    required this.day,
    this.status = LoadStatus.initial,
    this.people = const [],
    this.working,
    this.notice,
    this.left = const [],
  });

  final DateTime day;
  final LoadStatus status;
  final List<SchedulePerson> people;

  /// What is being changed: `slot-ID` or `day-STAFF_ID`.
  final String? working;

  /// A one-off message (what changed, or why not).
  final String? notice;

  /// Bookings left in times just closed: staff move or cancel them.
  final List<Booking> left;

  @override
  List<Object?> get props => [day, status, people, working, notice, left];
}

/// The day's times by person, closed and opened by hand: a doctor is ill, a master leaves early.
class ScheduleCubit extends Cubit<ScheduleState> {
  ScheduleCubit(this._repository, DateTime day) : super(ScheduleState(day: DateTime(day.year, day.month, day.day)));

  final JoopRepository _repository;

  Future<void> showDay(DateTime day) async {
    final d = DateTime(day.year, day.month, day.day);
    emit(ScheduleState(day: d, status: LoadStatus.loading, people: d == state.day ? state.people : const []));
    try {
      final people = await _repository.schedule(d);
      if (state.day == d) {
        emit(ScheduleState(day: d, status: LoadStatus.success, people: people));
      }
    } on ApiException catch (e) {
      if (state.day == d) {
        emit(ScheduleState(day: d, status: LoadStatus.failure, people: state.people, notice: e.message));
      }
    }
  }

  Future<void> setSlot(ScheduleSlot slot, bool open) =>
      _change('slot-${slot.id}', () => _repository.setSlotOpen(slot.id, open), open);

  Future<void> setDay(SchedulePerson person, bool open) =>
      _change('day-${person.id}', () => _repository.setDayOpen(person.id, state.day, open), open);

  Future<void> _change(String key, Future<ScheduleChange> Function() call, bool open) async {
    if (state.working != null) return;
    emit(ScheduleState(day: state.day, status: state.status, people: state.people, working: key));
    String notice;
    var left = const <Booking>[];
    try {
      final change = await call();
      notice = open ? S.current.openedTimes(change.changed, change.offered) : S.current.closedTimes(change.changed);
      left = change.bookings;
    } on ApiException catch (e) {
      notice = e.message;
    }
    final day = state.day;
    try {
      final people = await _repository.schedule(day);
      emit(ScheduleState(day: day, status: LoadStatus.success, people: people, notice: notice, left: left));
    } on ApiException {
      emit(ScheduleState(day: day, status: state.status, people: state.people, notice: notice, left: left));
    }
  }
}
