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

  @override
  List<Object?> get props => [status, services, error, switching, notice, saving];
}

/// The business's price list, as the AI quotes it.
class ServicesCubit extends Cubit<ServicesState> {
  ServicesCubit(this._repository) : super(const ServicesState());

  final JoopRepository _repository;

  Future<void> load() async {
    emit(ServicesState(status: LoadStatus.loading, services: state.services));
    try {
      emit(ServicesState(status: LoadStatus.success, services: await _repository.services()));
    } on ApiException catch (e) {
      emit(ServicesState(status: LoadStatus.failure, services: state.services, error: e.message));
    }
  }

  Future<void> setAvailable(Service item, bool available) async {
    if (state.switching != null) return;
    emit(ServicesState(status: state.status, services: state.services, switching: item.id));
    try {
      final updated = await _repository.setAvailable(item.id, available);
      emit(ServicesState(
          status: state.status, services: [for (final x in state.services) x.id == updated.id ? updated : x]));
    } on ApiException catch (e) {
      emit(ServicesState(status: state.status, services: state.services, notice: e.message));
    }
  }

  /// A new row (`item` null) or the row's new name and price. True when the server took it.
  Future<bool> save(Service? item, ServiceDraft draft) =>
      _edit(() => item == null ? _repository.addService(draft) : _repository.updateService(item.id, draft));

  Future<bool> delete(Service item) => _edit(() => _repository.deleteService(item.id));

  /// The sign-up example out in one go; `done(n)` says how many rows went.
  Future<bool> deleteExample(String Function(int removed) done) => _edit(() async {
        final (removed, services) = await _repository.deleteExample();
        _afterNotice = done(removed);
        return services;
      });

  String? _afterNotice;

  Future<bool> _edit(Future<List<Service>> Function() call) async {
    if (state.saving) return false;
    emit(ServicesState(status: state.status, services: state.services, saving: true));
    try {
      final services = await call();
      emit(ServicesState(status: LoadStatus.success, services: services, notice: _afterNotice));
      return true;
    } on ApiException catch (e) {
      emit(ServicesState(status: state.status, services: state.services, notice: e.message));
      return false;
    } finally {
      _afterNotice = null;
    }
  }
}
