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

  int get openCount => state.items.where((o) => o.isOpen).length;

  Future<void> load() async {
    emit(state.copyWith(status: LoadStatus.loading));
    try {
      emit(state.copyWith(status: LoadStatus.success, items: await _repository.orders()));
    } on ApiException catch (e) {
      emit(state.copyWith(status: LoadStatus.failure, error: e.message));
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
