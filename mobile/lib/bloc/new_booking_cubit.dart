import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../core/strings.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class NewBookingState extends Equatable {
  const NewBookingState({
    required this.day,
    this.status = LoadStatus.initial,
    this.slots = const [],
    this.selected,
    this.saving = false,
    this.error,
    this.booked,
  });

  final DateTime day;
  final LoadStatus status;
  final List<FreeSlot> slots;
  final FreeSlot? selected;
  final bool saving;
  final String? error;

  /// Set once the booking is made; the screen closes with it.
  final Booking? booked;

  NewBookingState copyWith({
    DateTime? day,
    LoadStatus? status,
    List<FreeSlot>? slots,
    FreeSlot? Function()? selected,
    bool? saving,
    String? Function()? error,
    Booking? booked,
  }) =>
      NewBookingState(
        day: day ?? this.day,
        status: status ?? this.status,
        slots: slots ?? this.slots,
        selected: selected != null ? selected() : this.selected,
        saving: saving ?? this.saving,
        error: error != null ? error() : this.error,
        booked: booked ?? this.booked,
      );

  @override
  List<Object?> get props => [day, status, slots, selected, saving, error, booked];
}

/// Booking a customer who phoned or walked in: a day, one of its free times, the customer's name and phone.
class NewBookingCubit extends Cubit<NewBookingState> {
  NewBookingCubit(this._repository, DateTime day) : super(NewBookingState(day: DateTime(day.year, day.month, day.day)));

  final JoopRepository _repository;

  Future<void> showDay(DateTime day) async {
    final d = DateTime(day.year, day.month, day.day);
    emit(NewBookingState(day: d, status: LoadStatus.loading));
    try {
      final slots = await _repository.freeSlots(d);
      if (state.day != d) return; // another day was picked meanwhile
      emit(state.copyWith(status: LoadStatus.success, slots: slots));
    } on ApiException catch (e) {
      if (state.day != d) return;
      emit(state.copyWith(status: LoadStatus.failure, error: () => e.message));
    }
  }

  void choose(FreeSlot slot) => emit(state.copyWith(selected: () => slot, error: () => null));

  Future<void> book({required String name, String phone = '', String service = ''}) async {
    final slot = state.selected;
    if (slot == null || state.saving) return;
    if (name.trim().isEmpty) {
      emit(state.copyWith(error: () => S.current.nameNeeded));
      return;
    }
    emit(state.copyWith(saving: true, error: () => null));
    try {
      final booking = await _repository.book(slotId: slot.id, name: name.trim(), phone: phone.trim(), service: service.trim());
      emit(state.copyWith(saving: false, booked: booking));
    } on ApiException catch (e) {
      if (e.statusCode != 409) {
        emit(state.copyWith(saving: false, error: () => e.message)); // a mistyped phone: fix it and send again
        return;
      }
      // The time went meanwhile (the AI booked it): show the day as it is now, keep the typed fields.
      await showDay(state.day);
      emit(state.copyWith(error: () => e.message));
    }
  }
}
