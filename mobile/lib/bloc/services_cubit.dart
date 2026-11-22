import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class ServicesState extends Equatable {
  const ServicesState(
      {this.status = LoadStatus.initial, this.services = const [], this.error, this.switching, this.notice, this.saving = false});

  final LoadStatus status;
  final List<Service> services;
  final String? error;

  /// The item whose stop-list switch is in flight.
  final int? switching;

  /// A one-off message for a snackbar (a switch the server refused).
  final String? notice;

  /// An edit of the price list is in flight.
  final bool saving;

  /// The same state with some fields changed. `notice` is one-off, so it is dropped unless given; `switching` and
  /// `saving` stay as they are, so one call in flight never clears the other's flag.
  ServicesState copy({LoadStatus? status, List<Service>? services, String? error, Object? switching = _keep, String? notice, bool? saving}) =>
      ServicesState(
        status: status ?? this.status,
        services: services ?? this.services,
        error: error ?? this.error,
        switching: identical(switching, _keep) ? this.switching : switching as int?,
        notice: notice,
        saving: saving ?? this.saving,
      );

  static const _keep = Object();

  @override
  List<Object?> get props => [status, services, error, switching, notice, saving];
}

/// The business's price list, as the AI quotes it.
class ServicesCubit extends Cubit<ServicesState> {
  ServicesCubit(this._repository) : super(const ServicesState());

  final JoopRepository _repository;

  Future<void> load() async {
    emit(state.copy(status: LoadStatus.loading));
    try {
      final services = await _repository.services();
      emit(ServicesState(status: LoadStatus.success, services: services, switching: state.switching, saving: state.saving));
    } on ApiException catch (e) {
      emit(state.copy(status: LoadStatus.failure, error: e.message));
    }
  }

  Future<void> setAvailable(Service item, bool available) async {
    if (state.switching != null || state.saving) return;
    emit(state.copy(switching: item.id));
    try {
      final updated = await _repository.setAvailable(item.id, available);
      emit(state.copy(switching: null, services: [for (final x in state.services) x.id == updated.id ? updated : x]));
    } on ApiException catch (e) {
      emit(state.copy(switching: null, notice: e.message));
    }
  }

  /// A new row (`item` null) or the row's new name and price. Null when the server took it, else its refusal, for
  /// the edit sheet to show (a snackbar would sit behind it).
  Future<String?> save(Service? item, ServiceDraft draft) =>
      _edit(() => item == null ? _repository.addService(draft) : _repository.updateService(item.id, draft));

  Future<String?> delete(Service item) => _edit(() => _repository.deleteService(item.id));

  /// The sign-up example out in one go; `done(n)` says how many rows went. Shown as a snackbar, refusal included.
  Future<void> deleteExample(String Function(int removed) done) async {
    String? said;
    final refused = await _edit(() async {
      final (removed, services) = await _repository.deleteExample();
      said = done(removed);
      return services;
    }, notice: () => said);
    if (refused != null) emit(state.copy(notice: refused));
  }

  Future<String?> _edit(Future<List<Service>> Function() call, {String? Function()? notice}) async {
    if (state.saving) return null;
    emit(state.copy(saving: true));
    try {
      final services = await call();
      emit(state.copy(status: LoadStatus.success, services: services, saving: false, notice: notice?.call()));
      return null;
    } on ApiException catch (e) {
      emit(state.copy(saving: false));
      return e.message;
    }
  }
}
