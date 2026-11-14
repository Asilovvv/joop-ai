import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

/// A list loaded from the server, with one item being changed and a one-off message for a snackbar.
class WorkState<T> extends Equatable {
  const WorkState({this.status = LoadStatus.initial, this.items = const [], this.busyId, this.notice, this.error});

  final LoadStatus status;
  final List<T> items;
  final int? busyId;
  final String? notice;
  final String? error;

  WorkState<T> copyWith({LoadStatus? status, List<T>? items, int? busyId, bool clearBusy = false, String? notice, String? error}) =>
      WorkState<T>(
        status: status ?? this.status,
        items: items ?? this.items,
        busyId: clearBusy ? null : (busyId ?? this.busyId),
        notice: notice,
        error: error,
      );

  @override
  List<Object?> get props => [status, items, busyId, notice, error];
}

/// Orders the AI collected (cafes, shops, delivery), moved through the panel's steps.
class OrdersCubit extends Cubit<WorkState<Order>> {
  OrdersCubit(this._repository) : super(const WorkState());

  final JoopRepository _repository;

  /// Orders nobody has accepted yet: the tab's counter.
  int get newCount => state.items.where((o) => o.status == 'new').length;

  Future<void> load() async {
    emit(state.copyWith(status: LoadStatus.loading));
    try {
      emit(state.copyWith(status: LoadStatus.success, items: await _repository.orders()));
    } on ApiException catch (e) {
      emit(state.copyWith(status: LoadStatus.failure, error: e.message));
    }
  }

  /// A background check while the app is open: no spinner, no error message, and a notice for orders that came in.
  Future<void> refresh() async {
    if (state.status != LoadStatus.success || state.busyId != null) return;
    try {
      final rows = await _repository.orders();
      final known = {for (final o in state.items) o.id};
      final fresh = rows.where((o) => !known.contains(o.id) && o.status == 'new').toList();
      emit(state.copyWith(
        items: rows,
        notice: fresh.isEmpty
            ? null
            : fresh.length == 1
                ? 'Новый заказ №${fresh.single.id}'
                : 'Новых заказов: ${fresh.length}',
      ));
    } on ApiException {
      // The next check tries again.
    }
  }

  Future<void> move(Order order, OrderStep step) async {
    emit(state.copyWith(busyId: order.id));
    try {
      final result = await _repository.moveOrder(order.id, step.status);
      final told = switch (result.customerTold) {
        true => ' Клиенту отправлено сообщение.',
        false => ' Написать клиенту не получилось: ${result.why} Телефон: ${result.order.customerPhone}',
        null => '',
      };
      emit(state.copyWith(
        items: [for (final o in state.items) o.id == order.id ? result.order : o],
        clearBusy: true,
        notice: 'Заказ №${order.id}: ${result.order.label}.$told',
      ));
    } on ApiException catch (e) {
      emit(state.copyWith(clearBusy: true, error: e.message));
      await load(); // another person may have moved it: show what it is now
    }
  }
}

/// Requests for staff: questions the AI could not answer, bookings without a free slot, qualified leads.
class LeadsCubit extends Cubit<WorkState<Lead>> {
  LeadsCubit(this._repository) : super(const WorkState());

  final JoopRepository _repository;

  Future<void> load() async {
    emit(state.copyWith(status: LoadStatus.loading));
    try {
      emit(state.copyWith(status: LoadStatus.success, items: await _repository.leads()));
    } on ApiException catch (e) {
      emit(state.copyWith(status: LoadStatus.failure, error: e.message));
    }
  }

  /// New requests: the tab's counter.
  int get newCount => state.items.where((x) => !x.done).length;

  /// A background check while the app is open, as for orders.
  Future<void> refresh() async {
    if (state.status != LoadStatus.success || state.busyId != null) return;
    try {
      final rows = await _repository.leads();
      final known = {for (final x in state.items) x.id};
      final fresh = rows.where((x) => !known.contains(x.id) && !x.done).length;
      emit(state.copyWith(
        items: rows,
        notice: fresh == 0 ? null : (fresh == 1 ? 'Новая заявка' : 'Новых заявок: $fresh'),
      ));
    } on ApiException {
      // The next check tries again.
    }
  }

  Future<void> markDone(Lead lead) async {
    emit(state.copyWith(busyId: lead.id));
    try {
      final done = await _repository.closeLead(lead.id);
      emit(state.copyWith(
        items: [for (final x in state.items) x.id == lead.id ? done : x],
        clearBusy: true,
        notice: 'Заявка закрыта',
      ));
    } on ApiException catch (e) {
      emit(state.copyWith(clearBusy: true, error: e.message));
    }
  }
}
