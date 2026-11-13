import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

// ---------------------------------------------------------------- events

sealed class BookingsEvent extends Equatable {
  const BookingsEvent();

  @override
  List<Object?> get props => [];
}

/// Show the bookings of this day (the business's local date).
final class BookingsDayChanged extends BookingsEvent {
  const BookingsDayChanged(this.day);

  final DateTime day;

  @override
  List<Object?> get props => [day];
}

final class BookingsRefreshed extends BookingsEvent {
  const BookingsRefreshed();
}

final class BookingCancelRequested extends BookingsEvent {
  const BookingCancelRequested(this.bookingId);

  final int bookingId;

  @override
  List<Object?> get props => [bookingId];
}

// ---------------------------------------------------------------- state

class BookingsState extends Equatable {
  const BookingsState({
    required this.day,
    this.status = LoadStatus.initial,
    this.bookings = const [],
    this.cancelling,
    this.error,
    this.notice,
  });

  final DateTime day;
  final LoadStatus status;
  final List<Booking> bookings;

  /// The booking whose cancellation is in flight.
  final int? cancelling;
  final String? error;

  /// A one-off message for a snackbar, such as "Запись отменена".
  final String? notice;

  int get activeCount => bookings.where((b) => b.isActive).length;

  BookingsState copyWith({
    DateTime? day,
    LoadStatus? status,
    List<Booking>? bookings,
    int? cancelling,
    bool clearCancelling = false,
    String? error,
    String? notice,
  }) =>
      BookingsState(
        day: day ?? this.day,
        status: status ?? this.status,
        bookings: bookings ?? this.bookings,
        cancelling: clearCancelling ? null : (cancelling ?? this.cancelling),
        error: error,
        notice: notice,
      );

  @override
  List<Object?> get props => [day, status, bookings, cancelling, error, notice];
}

// ------------------------------------------------------------------ bloc

class BookingsBloc extends Bloc<BookingsEvent, BookingsState> {
  BookingsBloc(this._repository, {required DateTime today})
      : super(BookingsState(day: DateTime(today.year, today.month, today.day))) {
    on<BookingsDayChanged>((event, emit) => _load(emit, DateTime(event.day.year, event.day.month, event.day.day)));
    on<BookingsRefreshed>((event, emit) => _load(emit, state.day));
    on<BookingCancelRequested>(_onCancel);
  }

  final JoopRepository _repository;

  Future<void> _load(Emitter<BookingsState> emit, DateTime day) async {
    final sameDay = day == state.day;
    emit(state.copyWith(day: day, status: LoadStatus.loading, bookings: sameDay ? state.bookings : const []));
    try {
      final rows = await _repository.bookings(day);
      if (state.day != day) return; // the user moved on to another day meanwhile
      emit(state.copyWith(status: LoadStatus.success, bookings: rows));
    } on ApiException catch (e) {
      emit(state.copyWith(status: LoadStatus.failure, error: e.message));
    }
  }

  Future<void> _onCancel(BookingCancelRequested event, Emitter<BookingsState> emit) async {
    emit(state.copyWith(cancelling: event.bookingId));
    try {
      final updated = await _repository.cancel(event.bookingId);
      emit(state.copyWith(
        bookings: [for (final b in state.bookings) b.id == updated.id ? updated : b],
        clearCancelling: true,
        notice: 'Запись отменена, время снова свободно',
      ));
    } on ApiException catch (e) {
      emit(state.copyWith(clearCancelling: true, error: e.message));
    }
  }
}
