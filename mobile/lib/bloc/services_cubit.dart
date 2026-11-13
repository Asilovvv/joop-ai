import 'package:equatable/equatable.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../core/api_client.dart';
import '../data/joop_repository.dart';
import '../data/models.dart';
import 'load_status.dart';

class ServicesState extends Equatable {
  const ServicesState({this.status = LoadStatus.initial, this.services = const [], this.error});

  final LoadStatus status;
  final List<Service> services;
  final String? error;

  @override
  List<Object?> get props => [status, services, error];
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
}
